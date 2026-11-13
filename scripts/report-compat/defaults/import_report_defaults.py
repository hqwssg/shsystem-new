"""Import only report company defaults and default images. Dry-run unless --apply."""
from pathlib import Path
import argparse
import base64
import datetime
import getpass
import hashlib
import json
import os

PROFILE_FIELDS = {
    'legal_name', 'short_name', 'entity_code', 'default_compiler', 'carbon_department',
    'business_description', 'company_overview', 'process_description', 'default_org_boundary',
    'default_accounting_method', 'default_exclusion_note', 'default_approver', 'default_validator',
    'default_reviewer', 'default_checker', 'default_authors', 'default_equipment_json',
    'default_activity_prose_json', 'default_workload_json', 'default_chapter6_json', 'header_template',
}
ROLES = {'cover_logo', 'org_chart', 'office_location'}
AUDIT = 'report-defaults-patch'


def empty(value):
    return value is None or (isinstance(value, str) and value.strip() in ('', '{}', '[]', 'null'))


def profile_changes(existing, incoming, mode):
    if set(incoming) - PROFILE_FIELDS:
        raise ValueError('Unexpected profile fields')
    result = {}
    for key, value in incoming.items():
        if key.endswith('_json') and not isinstance(value, (str, type(None))):
            value = json.dumps(value, ensure_ascii=False)
        current = existing.get(key)
        if current == value:
            continue
        if key.endswith('_json') and not empty(current) and not empty(value):
            if json.loads(current) == json.loads(value):
                continue
        if mode == 'replace' or (empty(current) and not empty(value)):
            result[key] = value
    return result


def load_materials(folder):
    folder = folder.resolve()
    data = json.loads((folder / 'report-defaults.json').read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not data.get('companies'):
        raise ValueError('Unsupported or empty defaults package')
    for company in data['companies']:
        if set(company['profile']) != PROFILE_FIELDS:
            raise ValueError('Profile field allowlist mismatch')
        if company['profile']['entity_code'] != company['company_key']:
            raise ValueError('Company code mismatch')
        roles = [image['role'] for image in company['images']]
        if len(roles) != len(set(roles)) or not set(roles) <= ROLES:
            raise ValueError('Unexpected or duplicated image roles')
        for image in company['images']:
            path = (folder / image['path']).resolve()
            if not path.is_relative_to(folder / 'images'):
                raise ValueError('Image path must remain inside defaults/images')
            content = path.read_bytes()
            if len(content) != image['size_bytes'] or hashlib.sha256(content).hexdigest() != image['sha256']:
                raise ValueError('Image checksum mismatch: ' + image['role'])
            if image['mime_type'] == 'image/png':
                valid = content.startswith(b'\x89PNG\r\n\x1a\n')
            elif image['mime_type'] == 'image/jpeg':
                valid = content.startswith(b'\xff\xd8') and content.endswith(b'\xff\xd9')
            else:
                valid = False
            if not valid:
                raise ValueError('Unsupported image content')
            image['_content'] = content
    return data['companies']


def snapshot_json(value):
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode('ascii')}
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def import_defaults(connection, companies, mapping, *, apply=False, mode='missing', backup_dir=None, retire_unlisted_images=False):
    if mode not in ('missing', 'replace'):
        raise ValueError('Unsupported mode')
    if apply and backup_dir is None:
        raise ValueError('--backup-dir is required with --apply')
    if retire_unlisted_images and mode != 'replace':
        raise ValueError('--retire-unlisted-images requires --mode replace')
    keys = [company['company_key'] for company in companies]
    departments = [mapping.get(key, {}).get('dept_id') for key in keys]
    if len(set(keys)) != len(keys) or len(set(departments)) != len(departments):
        raise ValueError('Duplicate company key or target department')
    plans = []
    backups = []
    try:
        if not apply:
            with connection.cursor() as q:
                q.execute('SET TRANSACTION READ ONLY')
        connection.begin()
        with connection.cursor() as q:
            q.execute(
                "SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='report_file' "
                "AND COLUMN_NAME IN ('content','default_slot')"
            )
            columns = {row['name'] for row in q.fetchall()}
            q.execute(
                "SELECT COUNT(*) AS total FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='report_file' "
                "AND INDEX_NAME='uq_report_file_default_slot'"
            )
            has_default_index = q.fetchone()['total'] > 0
            if columns != {'content', 'default_slot'} or not has_default_index:
                raise ValueError(
                    'report_file default-image schema is incomplete; apply '
                    'sql/carbon-report/V15__report_file_content.sql first'
                )
            for company in companies:
                target = mapping.get(company['company_key'], {})
                dept_id = target.get('dept_id')
                if type(dept_id) is not int or dept_id <= 0 or not target.get('expected_dept_name'):
                    raise ValueError('Fill target dept_id and expected_dept_name for ' + company['company_key'])
                q.execute("SELECT d.dept_id,d.dept_name FROM sys_dept d JOIN sys_carbon_company c ON c.dept_id=d.dept_id WHERE d.dept_id=%s AND d.del_flag='0' AND d.status='0'", (dept_id,))
                registered = q.fetchall()
                if len(registered) != 1 or registered[0]['dept_name'] != target['expected_dept_name']:
                    raise ValueError('Target company is unregistered, inactive or name differs; nothing committed')
                lock = ' FOR UPDATE' if apply else ''
                q.execute('SELECT * FROM report_dept_profile WHERE dept_id=%s' + lock, (dept_id,))
                profiles = q.fetchall()
                if len(profiles) > 1:
                    raise ValueError('Duplicate company profiles; resolve manually first')
                previous = profiles[0] if profiles else {}
                if previous.get('entity_code') and previous['entity_code'] != company['company_key']:
                    expected = target.get('expected_existing_entity_code')
                    if expected != previous['entity_code'] or expected != 'SH-' + str(dept_id):
                        raise ValueError('Existing profile entity_code differs; explicitly verify the SH-dept placeholder first')
                changes = profile_changes(previous, company['profile'], mode)
                if previous.get('entity_code') and previous['entity_code'] != company['company_key']:
                    changes['entity_code'] = company['company_key']
                images = []
                for image in company['images']:
                    q.execute("SELECT * FROM report_file WHERE dept_id=%s AND kind='default' AND role=%s" + lock, (dept_id, image['role']))
                    current = q.fetchall()
                    if len(current) > 1 or (current and current[0].get('report_id') is not None):
                        raise ValueError('Ambiguous default image ownership; resolve manually first')
                    old = current[0] if current else None
                    same = old and old.get('sha256') == image['sha256'] and old.get('content') == image['_content']
                    missing = old and not old.get('content') and not old.get('object_key')
                    action = 'insert' if old is None else 'replace' if not same and (mode == 'replace' or missing) else 'keep'
                    images.append((image, old, action))
                retiring = []
                if retire_unlisted_images:
                    q.execute("SELECT * FROM report_file WHERE dept_id=%s AND kind='default'" + lock, (dept_id,))
                    desired = {image['role'] for image in company['images']}
                    retiring = [row for row in q.fetchall() if row['role'] in ROLES and row['role'] not in desired]
                    if any(row.get('report_id') is not None for row in retiring):
                        raise ValueError('Default image is attached to a report; refusing retirement')
                plans.append({'company_key':company['company_key'], 'dept_id':dept_id, 'profile_action':'insert' if not previous else 'update' if changes else 'keep',
                              'profile_fields':sorted(changes), 'images':[{ 'role':v[0]['role'], 'action':v[2]} for v in images],
                              'retired_images':[{'id':row['id'],'role':row['role']} for row in retiring]})
                backups.append({'company_key':company['company_key'],'dept_id':dept_id,'profile':previous or None,'images':[v[1] for v in images if v[1]]+retiring})
                company['_plan'] = (dept_id, previous, changes, images, retiring)
            backup_file = None
            if apply:
                directory = Path(backup_dir)
                directory.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                backup_file = directory / ('report-defaults-before-' + stamp + '.json')
                with backup_file.open('x', encoding='utf-8') as file:
                    json.dump({'mode':mode, 'plans':plans, 'before':backups}, file, ensure_ascii=False, indent=2, default=snapshot_json)
                for company in companies:
                    dept_id, previous, changes, images, retiring = company['_plan']
                    if not previous:
                        keys = sorted(company['profile'])
                        values = profile_changes({}, company['profile'], 'replace')
                        q.execute('INSERT INTO report_dept_profile (dept_id,' + ','.join(keys) + ',version,create_by,create_time,update_by,update_time) VALUES (' + ','.join(['%s']*(len(keys)+3)) + ',NOW(),%s,NOW())',
                                  [dept_id] + [values.get(key) for key in keys] + [1, AUDIT, AUDIT])
                    elif changes:
                        keys = sorted(changes)
                        q.execute('UPDATE report_dept_profile SET ' + ','.join(key+'=%s' for key in keys) + ',version=COALESCE(version,0)+1,update_by=%s,update_time=NOW() WHERE dept_id=%s',
                                  [changes[key] for key in keys] + [AUDIT,dept_id])
                    for image, old, action in images:
                        if action == 'keep':
                            continue
                        values = [image['filename'],image['mime_type'],image['size_bytes'],image['sha256'],image['_content'],AUDIT]
                        if action == 'replace':
                            # Keep the original ID and bytes for old generation snapshots.
                            q.execute("UPDATE report_file SET kind='archived_default',update_by=%s,update_time=NOW() WHERE id=%s AND dept_id=%s AND kind='default' AND report_id IS NULL",
                                      [AUDIT,old['id'],dept_id])
                            if q.rowcount != 1:
                                raise ValueError('Default image replacement lost ownership guard')
                        q.execute("INSERT INTO report_file (dept_id,report_id,kind,role,object_key,snapshot_sha256,original_name,mime_type,size_bytes,sha256,content,create_by,create_time,update_by,update_time) VALUES (%s,NULL,'default',%s,'','',%s,%s,%s,%s,%s,%s,NOW(),%s,NOW())",
                                  [dept_id,image['role']] + values + [AUDIT])
                    for row in retiring:
                        q.execute("UPDATE report_file SET kind='archived_default',update_by=%s,update_time=NOW() WHERE id=%s AND dept_id=%s AND kind='default' AND report_id IS NULL",
                                  [AUDIT,row['id'],dept_id])
                        if q.rowcount != 1:
                            raise ValueError('Default image retirement lost ownership guard')
        if apply:
            connection.commit()
        else:
            connection.rollback()
        return {'applied':apply,'mode':mode,'plans':plans,'backup_file':str(backup_file) if backup_file else None}
    except Exception:
        connection.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True)
    parser.add_argument('--port',type=int,default=3306)
    parser.add_argument('--database',required=True)
    parser.add_argument('--user',required=True)
    parser.add_argument('--password-env',help='Read password from this environment variable; otherwise prompt')
    parser.add_argument('--company-map',type=Path,required=True)
    parser.add_argument('--mode',choices=['missing','replace'],default='missing')
    parser.add_argument('--retire-unlisted-images',action='store_true',help='With replace, archive unlisted default image roles without deleting their bytes')
    parser.add_argument('--apply',action='store_true',help='Write to the database; omitted means preview only')
    parser.add_argument('--backup-dir',type=Path)
    args=parser.parse_args()
    import pymysql
    password=os.environ[args.password_env] if args.password_env else getpass.getpass('Database password: ')
    companies=load_materials(Path(__file__).resolve().parent)
    mapping=json.loads(args.company_map.read_text(encoding='utf-8'))
    connection=pymysql.connect(host=args.host,port=args.port,database=args.database,user=args.user,password=password,charset='utf8mb4',autocommit=False,cursorclass=pymysql.cursors.DictCursor)
    try:
        result=import_defaults(connection,companies,mapping,apply=args.apply,mode=args.mode,backup_dir=args.backup_dir,retire_unlisted_images=args.retire_unlisted_images)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
