"""Build an image-only, self-contained missing-only MySQL 8 initializer."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json


def literal(text):
    return "CONVERT(X'"+str(text).encode('utf-8').hex()+"' USING utf8mb4)"


def build(output):
    folder=Path(__file__).resolve().parent
    defaults=folder.parent/'defaults'
    spec=importlib.util.spec_from_file_location('defaults_loader',defaults/'import_report_defaults.py')
    loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
    companies=loader.load_materials(defaults)
    if len(companies)!=3 or any({i['role'] for i in c['images']}!=loader.ROLES for c in companies):
        raise ValueError('Expected three verified roles for each company')
    payload=[]
    for company in companies:
        payload.append('INSERT INTO tmp_cr_image_company (company_key,dept_name) VALUES ('+
                       ','.join(literal(v) for v in [company['company_key'],company['company_name']])+');')
        for image in company['images']:
            values=[literal(v) for v in [company['company_key'],image['role'],image['filename'],image['mime_type'],image['sha256']]]
            payload.append('INSERT INTO tmp_cr_image (company_key,role,filename,mime_type,sha256,size_bytes,content) VALUES ('+
                           ','.join(values)+','+str(image['size_bytes'])+",X'"+image['_content'].hex()+"');")
    sql=r'''-- Report default images only. MySQL 8.x. Select the intended database first.
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
DELIMITER //
DROP PROCEDURE IF EXISTS cr_init_images_20261022_v1//
CREATE PROCEDURE cr_init_images_20261022_v1()
SQL SECURITY INVOKER
BEGIN
 DECLARE v_n INT DEFAULT 0;
 DECLARE v_added INT DEFAULT 0;
 DECLARE v_lock INT DEFAULT 0;
 DECLARE v_lock_name VARCHAR(64);
 DECLARE EXIT HANDLER FOR SQLEXCEPTION
 BEGIN
  ROLLBACK;
  DROP TEMPORARY TABLE IF EXISTS tmp_cr_image;
  DROP TEMPORARY TABLE IF EXISTS tmp_cr_image_company;
  IF v_lock=1 THEN DO RELEASE_LOCK(v_lock_name); END IF;
  RESIGNAL;
 END;
 IF DATABASE() IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Select a target database first'; END IF;
 SET v_lock_name=CONCAT('cr-images:',LEFT(SHA2(DATABASE(),256),40));
 SELECT GET_LOCK(v_lock_name,30) INTO v_lock;
 IF COALESCE(v_lock,0)<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Image initialization is already running'; END IF;
 SELECT COUNT(*) INTO v_n FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='report_file'
   AND COLUMN_NAME IN ('id','dept_id','report_id','kind','role','object_key','snapshot_sha256',
      'original_name','mime_type','size_bytes','sha256','content','create_by','create_time','update_by','update_time');
 IF v_n<>16 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Report file schema is not ready'; END IF;
 IF NOT EXISTS(SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()
  AND TABLE_NAME='report_file' AND ENGINE='InnoDB') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Report files must use InnoDB';
 END IF;
 DROP TEMPORARY TABLE IF EXISTS tmp_cr_image;
 DROP TEMPORARY TABLE IF EXISTS tmp_cr_image_company;
 CREATE TEMPORARY TABLE tmp_cr_image_company (
  company_key VARCHAR(64) PRIMARY KEY,dept_name VARCHAR(128) NOT NULL,dept_id BIGINT NULL
 ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
 CREATE TEMPORARY TABLE tmp_cr_image (
  company_key VARCHAR(64) NOT NULL,role VARCHAR(32) NOT NULL,filename VARCHAR(255) NOT NULL,
  mime_type VARCHAR(128) NOT NULL,sha256 CHAR(64) NOT NULL,size_bytes BIGINT NOT NULL,content LONGBLOB NOT NULL,
  dept_id BIGINT NULL,old_id BIGINT NULL,fill_missing INT NOT NULL DEFAULT 0,
  PRIMARY KEY(company_key,role)
 ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
__PAYLOAD__
 IF EXISTS(SELECT 1 FROM tmp_cr_image WHERE size_bytes<>OCTET_LENGTH(content) OR sha256<>SHA2(content,256)) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Embedded image size or hash mismatch';
 END IF;
 START TRANSACTION;
 SELECT COUNT(*) INTO v_n FROM (
  SELECT s.company_key FROM tmp_cr_image_company s LEFT JOIN sys_dept d
   ON BINARY d.dept_name=BINARY s.dept_name AND d.status='0' AND d.del_flag='0'
   LEFT JOIN sys_carbon_company c ON c.dept_id=d.dept_id
   GROUP BY s.company_key HAVING COUNT(c.dept_id)<>1
 ) invalid_company;
 IF v_n<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Each company must match exactly one active registered company'; END IF;
 UPDATE tmp_cr_image_company s JOIN sys_dept d ON BINARY d.dept_name=BINARY s.dept_name
  AND d.status='0' AND d.del_flag='0' JOIN sys_carbon_company c ON c.dept_id=d.dept_id SET s.dept_id=d.dept_id;
 SELECT d.dept_id AS locked_company_id FROM sys_dept d JOIN tmp_cr_image_company s ON s.dept_id=d.dept_id FOR UPDATE;
 SELECT p.id AS locked_profile_id FROM report_dept_profile p JOIN tmp_cr_image_company s ON s.dept_id=p.dept_id FOR UPDATE;
 SELECT COUNT(*) INTO v_n FROM (
  SELECT s.company_key FROM tmp_cr_image_company s LEFT JOIN report_dept_profile p ON p.dept_id=s.dept_id
   GROUP BY s.company_key HAVING COUNT(p.id)<>1
 ) invalid_profile;
 IF v_n<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Exactly one existing profile per company is required'; END IF;
 IF EXISTS(SELECT 1 FROM report_dept_profile p JOIN tmp_cr_image_company s ON s.dept_id=p.dept_id
   WHERE BINARY TRIM(COALESCE(p.entity_code,'')) NOT IN (BINARY '',BINARY s.company_key,BINARY CONCAT('SH-',s.dept_id))) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Company profile identity conflict';
 END IF;
 UPDATE tmp_cr_image s JOIN tmp_cr_image_company c ON c.company_key=s.company_key SET s.dept_id=c.dept_id;
 SELECT f.id AS locked_image_id FROM report_file f JOIN tmp_cr_image s ON s.dept_id=f.dept_id
   AND BINARY s.role=BINARY f.role WHERE f.kind='default' FOR UPDATE;
 SELECT COUNT(*) INTO v_n FROM (
  SELECT s.company_key,s.role FROM tmp_cr_image s LEFT JOIN report_file f ON f.dept_id=s.dept_id
    AND f.kind='default' AND BINARY f.role=BINARY s.role
  GROUP BY s.company_key,s.role HAVING COUNT(f.id)>1 OR COUNT(f.report_id)>0
 ) invalid_image;
 IF v_n<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Duplicate defaults or report-bound default image; nothing committed'; END IF;
 IF EXISTS(SELECT 1 FROM report_file f JOIN tmp_cr_image s ON f.dept_id=s.dept_id AND BINARY f.role=BINARY s.role
   WHERE f.kind='default' AND COALESCE(OCTET_LENGTH(f.content),0)>0
   AND (f.size_bytes IS NULL OR f.size_bytes<>OCTET_LENGTH(f.content) OR f.sha256 IS NULL
        OR LOWER(TRIM(f.sha256))<>SHA2(f.content,256))) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Existing image checksum mismatch; manual review required';
 END IF;
 UPDATE tmp_cr_image s LEFT JOIN report_file f ON f.dept_id=s.dept_id AND f.kind='default'
  AND BINARY f.role=BINARY s.role SET s.old_id=f.id,
   s.fill_missing=CASE WHEN f.id IS NULL OR (COALESCE(OCTET_LENGTH(f.content),0)=0
    AND NULLIF(TRIM(f.object_key),'') IS NULL) THEN 1 ELSE 0 END;
 SELECT COUNT(*) INTO v_added FROM tmp_cr_image WHERE fill_missing=1;
 -- Preserve old IDs and bytes for any already generated report snapshots.
 UPDATE report_file f JOIN tmp_cr_image s ON f.id=s.old_id
  SET f.kind='archived_default',f.update_by='report-images-20261022',f.update_time=NOW()
  WHERE s.fill_missing=1 AND f.kind='default' AND f.report_id IS NULL;
 INSERT INTO report_file (dept_id,report_id,kind,role,object_key,snapshot_sha256,original_name,mime_type,
  size_bytes,sha256,content,create_by,create_time,update_by,update_time)
 SELECT s.dept_id,NULL,'default',s.role,'','',s.filename,s.mime_type,s.size_bytes,s.sha256,s.content,
  'report-images-20261022',NOW(),'report-images-20261022',NOW() FROM tmp_cr_image s WHERE s.fill_missing=1;
 COMMIT;
 SELECT 'REPORT_IMAGES_INIT_OK' AS status,DATABASE() AS target_database,v_added AS images_inserted;
 SELECT s.company_key,s.dept_id,s.role,f.id,f.original_name,f.size_bytes,OCTET_LENGTH(f.content) AS content_bytes,
  CASE WHEN s.fill_missing=1 THEN 'INITIALIZED'
       WHEN COALESCE(OCTET_LENGTH(f.content),0)=0 THEN 'EXTERNAL_REFERENCE_KEPT'
       ELSE 'EXISTING_IMAGE_KEPT' END AS action,
  CASE WHEN COALESCE(OCTET_LENGTH(f.content),0)>0 THEN 'CONTENT_OK' ELSE 'EXTERNAL_REFERENCE_CHECK' END AS image_check
  FROM tmp_cr_image s JOIN report_file f ON f.dept_id=s.dept_id AND BINARY f.role=BINARY s.role
  WHERE f.kind='default' ORDER BY s.company_key,s.role;
 DROP TEMPORARY TABLE tmp_cr_image;
 DROP TEMPORARY TABLE tmp_cr_image_company;
 DO RELEASE_LOCK(v_lock_name);
END//
CALL cr_init_images_20261022_v1()//
DROP PROCEDURE cr_init_images_20261022_v1//
DELIMITER ;
'''.replace('__PAYLOAD__','\n'.join(payload))
    output.mkdir(parents=True,exist_ok=True)
    (output/'init_report_images.sql').write_text(sql,encoding='ascii',newline='\n')
    backup_where="kind='default' AND dept_id IN (SELECT dept_id FROM sys_dept WHERE BINARY dept_name IN ("+','.join(
        "X'"+c['company_name'].encode('utf-8').hex()+"'" for c in companies)+'))'
    runner=(folder/'runner-template.sh').read_text(encoding='ascii').replace('__EMBEDDED_SQL__',sql).replace('__BACKUP_WHERE__',backup_where)
    (output/'init_report_images.sh').write_text(runner,encoding='ascii',newline='\n')
    manifest=dict(scope='default-images-only',companies=[dict(company_key=c['company_key'],images=[
        {k:v for k,v in i.items() if k!='_content'} for i in c['images']]) for c in companies])
    for p in output.glob('init_report_images.*'):
        manifest[p.name]=dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().output),ensure_ascii=False,indent=2))
