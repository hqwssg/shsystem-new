"""Build a self-contained, missing-only equipment initializer for MySQL 8."""
from pathlib import Path
import argparse
import hashlib
import json


def literal(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return "CONVERT(X'" + value.encode('utf-8').hex() + "' USING utf8mb4)"


def build(output):
    folder = Path(__file__).resolve().parent
    data = json.loads((folder / 'equipment-defaults.json').read_text(encoding='utf-8'))
    assert data['schema_version'] == 1 and len(data['companies']) == 3
    payload = []
    for c in data['companies']:
        rows = c['equipment']
        assert rows and all(set(r) == {'name','category','quantity','unit','model','energy_type','remark'} for r in rows)
        assert all(r['quantity'] is None or r['quantity'] >= 0 for r in rows)
        payload.append('INSERT INTO tmp_cr_equipment (company_key,dept_name,equipment_json) VALUES ('
                       + ','.join(literal(v) for v in [c['company_key'],c['company_name'],rows]) + ');')
    sql = r'''-- Equipment reference defaults only. MySQL 8.x; select target database first.
-- Existing nonempty equipment and all report/calculation/account/image rows are preserved.
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
DELIMITER //
DROP PROCEDURE IF EXISTS cr_init_equipment_20261022_v1//
CREATE PROCEDURE cr_init_equipment_20261022_v1()
SQL SECURITY INVOKER
BEGIN
    DECLARE v_n INT DEFAULT 0;
    DECLARE v_changed INT DEFAULT 0;
    DECLARE v_lock INT DEFAULT 0;
    DECLARE v_lock_name VARCHAR(64);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        DROP TEMPORARY TABLE IF EXISTS tmp_cr_equipment;
        IF v_lock=1 THEN DO RELEASE_LOCK(v_lock_name); END IF;
        RESIGNAL;
    END;
    IF DATABASE() IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Select a target database first'; END IF;
    SET v_lock_name=CONCAT('cr-equipment:',LEFT(SHA2(DATABASE(),256),40));
    SELECT GET_LOCK(v_lock_name,30) INTO v_lock;
    IF COALESCE(v_lock,0)<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Equipment initialization is already running'; END IF;
    SELECT COUNT(*) INTO v_n FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='report_dept_profile'
        AND COLUMN_NAME IN ('id','dept_id','entity_code','default_equipment_json','version','update_by','update_time');
    IF v_n<>7 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Report profile schema is not ready'; END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()
        AND TABLE_NAME='report_dept_profile' AND ENGINE='InnoDB') THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Report profiles must use InnoDB';
    END IF;
    DROP TEMPORARY TABLE IF EXISTS tmp_cr_equipment;
    CREATE TEMPORARY TABLE tmp_cr_equipment (
      company_key VARCHAR(64) PRIMARY KEY,dept_name VARCHAR(128) NOT NULL,
      dept_id BIGINT NULL,equipment_json LONGTEXT NOT NULL,before_json LONGTEXT NULL,
      fill_missing INT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
__PAYLOAD__
    IF EXISTS (SELECT 1 FROM tmp_cr_equipment WHERE JSON_VALID(equipment_json)<>1) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Invalid embedded equipment JSON';
    END IF;
    START TRANSACTION;
    SELECT COUNT(*) INTO v_n FROM (
      SELECT s.company_key FROM tmp_cr_equipment s
      LEFT JOIN sys_dept d ON BINARY d.dept_name=BINARY s.dept_name AND d.status='0' AND d.del_flag='0'
      LEFT JOIN sys_carbon_company c ON c.dept_id=d.dept_id
      GROUP BY s.company_key HAVING COUNT(c.dept_id)<>1
    ) invalid_company;
    IF v_n<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Each company must match exactly one active registered company; nothing committed'; END IF;
    UPDATE tmp_cr_equipment s JOIN sys_dept d ON BINARY d.dept_name=BINARY s.dept_name AND d.status='0' AND d.del_flag='0'
      JOIN sys_carbon_company c ON c.dept_id=d.dept_id SET s.dept_id=d.dept_id;
    SELECT d.dept_id AS locked_company_id FROM sys_dept d JOIN tmp_cr_equipment s ON s.dept_id=d.dept_id FOR UPDATE;
    SELECT p.id AS locked_profile_id FROM report_dept_profile p JOIN tmp_cr_equipment s ON s.dept_id=p.dept_id FOR UPDATE;
    SELECT COUNT(*) INTO v_n FROM (
      SELECT s.company_key FROM tmp_cr_equipment s LEFT JOIN report_dept_profile p ON p.dept_id=s.dept_id
      GROUP BY s.company_key HAVING COUNT(p.id)<>1
    ) invalid_profile;
    IF v_n<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Initialize company profiles first; exactly one profile per company is required'; END IF;
    IF EXISTS (SELECT 1 FROM report_dept_profile p JOIN tmp_cr_equipment s ON s.dept_id=p.dept_id
      WHERE BINARY TRIM(COALESCE(p.entity_code,'')) NOT IN (BINARY '',BINARY s.company_key,BINARY CONCAT('SH-',s.dept_id))) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Company profile identity conflict; nothing committed';
    END IF;
    IF EXISTS (SELECT 1 FROM report_dept_profile p JOIN tmp_cr_equipment s ON s.dept_id=p.dept_id
      WHERE NULLIF(TRIM(p.default_equipment_json),'') IS NOT NULL AND TRIM(p.default_equipment_json)<>'null'
        AND JSON_VALID(p.default_equipment_json)<>1) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Existing equipment JSON is invalid; preserved without changes';
    END IF;
    IF EXISTS (SELECT 1 FROM report_dept_profile p JOIN tmp_cr_equipment s ON s.dept_id=p.dept_id
      WHERE NULLIF(TRIM(p.default_equipment_json),'') IS NOT NULL AND TRIM(p.default_equipment_json)<>'null'
        AND JSON_TYPE(p.default_equipment_json)<>'ARRAY') THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Existing equipment must be a JSON array; preserved without changes';
    END IF;
    UPDATE tmp_cr_equipment s JOIN report_dept_profile p ON p.dept_id=s.dept_id
      SET s.before_json=p.default_equipment_json,
          s.fill_missing=CASE WHEN NULLIF(TRIM(p.default_equipment_json),'') IS NULL OR TRIM(p.default_equipment_json)='null' THEN 1
                              WHEN JSON_LENGTH(p.default_equipment_json)=0 THEN 1 ELSE 0 END;
    UPDATE report_dept_profile p JOIN tmp_cr_equipment s ON s.dept_id=p.dept_id
      SET p.default_equipment_json=s.equipment_json,p.version=COALESCE(p.version,0)+1,
          p.update_by='cr-equipment-init-v1',p.update_time=NOW()
      WHERE s.fill_missing=1;
    SET v_changed=ROW_COUNT();
    COMMIT;
    SELECT 'REPORT_EQUIPMENT_INIT_OK' AS status,DATABASE() AS target_database,v_changed AS profiles_updated;
    SELECT s.company_key,p.dept_id,d.dept_name,JSON_LENGTH(p.default_equipment_json) AS equipment_rows,
      CASE WHEN s.fill_missing=1 THEN 'INITIALIZED' ELSE 'EXISTING_EQUIPMENT_KEPT' END AS action,
      SHA2(p.default_equipment_json,256) AS equipment_sha256,p.version
      FROM tmp_cr_equipment s JOIN report_dept_profile p ON p.dept_id=s.dept_id JOIN sys_dept d ON d.dept_id=s.dept_id
      ORDER BY s.company_key;
    DROP TEMPORARY TABLE tmp_cr_equipment;
    DO RELEASE_LOCK(v_lock_name);
END//
CALL cr_init_equipment_20261022_v1()//
DROP PROCEDURE cr_init_equipment_20261022_v1//
DELIMITER ;
'''.replace('__PAYLOAD__', '\n'.join(payload))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'init_report_equipment.sql').write_text(sql, encoding='ascii', newline='\n')
    runner = (folder / 'runner-template.sh').read_text(encoding='ascii').replace('__EMBEDDED_SQL__', sql)
    (output / 'init_report_equipment.sh').write_text(runner, encoding='ascii', newline='\n')
    manifest = {c['company_key']: {'rows':len(c['equipment']),'source_year':c['source_year'],
                'missing_quantity':sum(r['quantity'] is None for r in c['equipment'])} for c in data['companies']}
    for p in output.glob('init_report_equipment.*'):
        manifest[p.name] = {'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (output / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().output),ensure_ascii=False,indent=2))
