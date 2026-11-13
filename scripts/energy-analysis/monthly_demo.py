"""Local-only monthly analysis demo. Credentials are read from MYSQL_*; never stored in the manifest."""
import argparse, calendar, datetime, decimal, getpass, hashlib, json, os
from pathlib import Path
import pymysql

MARK = '本地演示-月度统计20261028'
BASE = 910028000
MONTH_TABLE = 'emission_collection_node_data_month'
COMPANY_NAMES = ['肃宁分公司', '原平分公司', '机辆分公司']


def canonical(row):
    return {k: str(v) if isinstance(v, (decimal.Decimal, datetime.date, datetime.datetime)) else v for k, v in row.items()}


def digest(row):
    return hashlib.sha256(json.dumps(canonical(row), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def select(cur, table, key):
    cur.execute('SELECT * FROM `' + table + '` WHERE ' + ' AND '.join('`' + k + '`=%s' for k in key), list(key.values()))
    return cur.fetchone()


def rows_for(companies):
    rows = []
    def add(table, key, **values):
        rows.append({'table': table, 'key': key, 'values': dict(key, **values)})
    for ci, company in enumerate(companies):
        cid, name = company['dept_id'], company['dept_name']
        b = BASE + ci * 1000
        template, root = b + 10, b + 20
        for j in range(2):
            add('sys_dept', {'dept_id': b + 700 + j}, parent_id=cid, ancestors=(company['ancestors'] + ',' + str(cid)).strip(','), dept_name='本地演示' + ('生产部' if j == 0 else '服务部'), status='0', del_flag='0', create_by=MARK)
            add('emission_energy_attribution_station', {'id': b + 710 + j}, name=MARK + '-' + name + '-' + str(j + 1) + '站', branch_company=name, created_by=1)
        add('emission_station_interval', {'id': b + 100}, name=MARK + '-' + name + '-电力范围', status=1, created_by=1)
        add('emission_concentrator', {'id': b + 101}, station_interval_id=b + 100, name=MARK + '-' + name + '-电力集中器', status=1, created_by=1)
        for prefix, offset in [('emission_fossil_fuel', 110), ('emission_purchased_heat', 120)]:
            add(prefix + '_collection_scope', {'id': b + offset}, scope_name=MARK + '-' + name + '-范围', created_by=1)
            add(prefix + '_collection_sub_scope', {'id': b + offset + 1}, collection_scope_id=b + offset, sub_scope_name=MARK + '-' + name + '-子范围', created_by=1)
        for j, (scope_type, offset) in enumerate([('electricity', 100), ('fossil', 110), ('heat', 120)]):
            add('sys_carbon_scope_owner', {'scope_type': scope_type, 'scope_id': b + offset}, company_dept_id=cid, created_by=1)
            add('sys_carbon_scope_grant', {'grant_id': b + 800 + j}, scope_type=scope_type, scope_id=b + offset, node_type='scope', node_id=b + offset, node_name=MARK, dept_id=cid, can_read=1, can_write=0, can_delegate=0, created_by=1)
        add('emission_template', {'id': template}, name=MARK + '-' + name, description=MARK + '；仅演示统计，不作为正式核算数据', created_by=1, template_type=2, dept_id=cid, enabled=1)
        add('emission_node', {'id': root}, template_id=template, name=MARK + '-总核算点', type_id=2, created_by=1)
        specs = [(1, 'electricity', 'MWh', '0.53', 'EC01', 'EC0101'), (2, 'diesel', 't', '3.145', 'EC01', 'EC0102'), (2, 'gasoline', 't', '3.043', 'EC03', 'EC0301'), (2, 'natural_gas', '10k_m3', '21.62', 'EC03', 'EC0301'), (3, 'heat', 'GJ', '0.11', 'EC03', 'EC0301')]
        for ei, (kind, energy, unit, factor, l1, l2) in enumerate(specs):
            point = b + 200 + ei
            table = {1: 'emission_meter_info', 2: 'emission_fossil_fuel_meter_info', 3: 'emission_purchased_heat_meter_info'}[kind]
            values = dict(name=MARK + '-' + name + '-' + energy, measurement_unit=unit, emission_subcategory=energy, energy_category_l1=l1, energy_category_l2=l2, energy_attribution_dept_id=b + 700 + ei % 2, energy_attribution_station_id=b + 710 + ei % 2, created_by=1, status=1, is_cumulative=0)
            values['point_id' if kind == 1 else 'sub_scope_id'] = b + (101 if kind == 1 else 111 if kind == 2 else 121)
            add(table, {'id': point}, **values)
            add('emission_node', {'id': b + 30 + ei}, template_id=template, parent_id=root, name=MARK + '-' + energy, type_id=3, created_by=1)
            add('emission_node_config', {'id': b + 40 + ei}, node_id=b + 30 + ei, collection_point_type=kind, collection_point_id=point, emission_subcategory=energy, measurement_unit=unit, created_by=1)
            for year in (2025, 2026):
                for month in range(1, 13):
                    if energy == 'natural_gas' and year == 2026 and month == 11:
                        continue  # Absent monthly row; deliberately not a zero.
                    raw = decimal.Decimal((ci + 1) * (ei + 1) * 10 + month) * decimal.Decimal('1.12' if year == 2026 else '1')
                    if energy == 'gasoline' and year == 2025 and month == 1: raw = decimal.Decimal(0)
                    adjusted = raw * decimal.Decimal('1.08')
                    status, description = 1, MARK + '；正常'
                    if energy == 'electricity' and month == 6: status, description = 3, MARK + '；演示估算补全'
                    if energy == 'diesel' and year == 2026 and month == 9: status, description = 2, MARK + '；该月份无数据，数值不可作为真实零值'
                    raw_energy = None if energy == 'heat' and year == 2026 and month == 5 else raw
                    data = dict(year=year, month=month, collection_point_type=kind, collection_point_id=point, emission_subcategory=energy, measurement_unit=unit, carbon_emission_unit='tCO2e', carbon_emission_factor=decimal.Decimal(factor), carbon_emission_factor_unit='tCO2e/' + unit, energy_category_l1=l1, energy_category_l2=l2, energy_measurement_value=raw_energy, carbon_emission=None if raw_energy is None else raw_energy * decimal.Decimal(factor), adjusted_energy_value=adjusted, adjusted_carbon_emission=adjusted * decimal.Decimal(factor), total_emission_calc_method=1 if month % 2 or energy == 'heat' else 2, data_status=status, data_missing_description=description, energy_attribution_dept_id=None if energy == 'diesel' and month == 12 else b + 700 + ei % 2, energy_attribution_station_id=None if energy == 'diesel' and month == 12 else b + 710 + ei % 2, created_by=1, updated_by=1)
                    add(MONTH_TABLE, {'id': b + 500 + ei * 24 + (year - 2025) * 12 + month}, **data)
        # Same electricity point referenced twice: analysis must count it once.
        add('emission_node', {'id': b + 90}, template_id=template, parent_id=root, name=MARK + '-重复引用校验', type_id=3, created_by=1)
        add('emission_node_config', {'id': b + 91}, node_id=b + 90, collection_point_type=1, collection_point_id=b + 200, created_by=1)
    return rows


def target(cur, database):
    cur.execute('SELECT @@server_uuid AS server_uuid, DATABASE() AS database_name')
    return cur.fetchone()


def check_references(cur, entries):
    """Refuse FK cascades/SET NULL that would touch anything outside this manifest."""
    cur.execute('SELECT table_name AS child_table,column_name AS child_column,referenced_table_name AS parent_table,referenced_column_name AS parent_column,constraint_name AS fk_name FROM information_schema.key_column_usage WHERE referenced_table_schema=DATABASE() ORDER BY ordinal_position')
    constraints = {}
    for row in cur.fetchall():
        constraints.setdefault((row['child_table'], row['parent_table'], row['fk_name']), []).append((row['child_column'], row['parent_column']))
    known = {}
    for entry in entries: known.setdefault(entry['table'], []).append(entry['key'])
    quote = lambda name: '`' + name.replace('`', '``') + '`'
    for entry in entries:
        parent = select(cur, entry['table'], entry['key'])
        if not parent: continue
        for (child, parent_table, _), columns in constraints.items():
            if parent_table != entry['table']: continue
            cur.execute('SELECT * FROM ' + quote(child) + ' WHERE ' + ' AND '.join(quote(c) + '=%s' for c, _ in columns), [parent[p] for _, p in columns])
            for row in cur.fetchall():
                if not any(all(row[k] == v for k, v in key.items()) for key in known.get(child, [])):
                    raise RuntimeError('External reference in ' + child + '; refusing cleanup')


def run(connection, action, manifest_path):
    manifest_path = Path(manifest_path)
    connection.begin()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cur:
            identity = target(cur, None)
            old = json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else None
            if old and (old['marker'] != MARK or old['target'] != identity): raise RuntimeError('Manifest does not belong to this demo/database')
            if action in ('verify', 'clean'):
                if not old: raise RuntimeError('Explicit demo manifest required')
                for entry in old['rows']:
                    current = select(cur, entry['table'], entry['key'])
                    if current and digest(current) != entry['sha256']: raise RuntimeError('Demo row changed; review manually: ' + entry['table'] + str(entry['key']))
                    if not current and action == 'verify': raise RuntimeError('Demo row missing: ' + str(entry['key']))
                if action == 'clean':
                    check_references(cur, old['rows'])
                    node_ids = {e['key']['id'] for e in old['rows'] if e['table'] == 'emission_node'}
                    for tid in old['template_ids']:
                        cur.execute('SELECT COUNT(*) AS n FROM emission_calculation_template WHERE template_id=%s', (tid,))
                        if cur.fetchone()['n']: raise RuntimeError('Demo template has calculation tasks; refusing cleanup')
                        cur.execute('SELECT id FROM emission_node WHERE template_id=%s', (tid,))
                        if any(r['id'] not in node_ids for r in cur.fetchall()): raise RuntimeError('New nodes in demo template; refusing cleanup')
                    monthly_ids = {e['key']['id'] for e in old['rows'] if e['table'] == MONTH_TABLE}
                    config_ids = {e['key']['id'] for e in old['rows'] if e['table'] == 'emission_node_config'}
                    for kind, table in [(1, 'emission_meter_info'), (2, 'emission_fossil_fuel_meter_info'), (3, 'emission_purchased_heat_meter_info')]:
                        for point in (e['key']['id'] for e in old['rows'] if e['table'] == table):
                            cur.execute('SELECT id FROM ' + MONTH_TABLE + ' WHERE collection_point_type=%s AND collection_point_id=%s', (kind, point))
                            if any(r['id'] not in monthly_ids for r in cur.fetchall()): raise RuntimeError('New monthly results reference demo point; refusing cleanup')
                            cur.execute('SELECT id FROM emission_node_config WHERE collection_point_type=%s AND collection_point_id=%s', (kind, point))
                            if any(r['id'] not in config_ids for r in cur.fetchall()): raise RuntimeError('Another template references demo point; refusing cleanup')
                            cur.execute('SELECT COUNT(*) AS n FROM emission_collection_record WHERE collection_point_type=%s AND collection_point_id=%s', (kind, point))
                            if cur.fetchone()['n']: raise RuntimeError('Collection records reference demo point; refusing cleanup')
                    for entry in reversed(old['rows']):
                        cur.execute('DELETE FROM `' + entry['table'] + '` WHERE ' + ' AND '.join('`' + k + '`=%s' for k in entry['key']), list(entry['key'].values()))
                connection.commit()
                return {'action': action, 'rows': len(old['rows']), 'monthly_rows': sum(e['table'] == MONTH_TABLE for e in old['rows'])}
            cur.execute("SELECT d.* FROM sys_carbon_company c JOIN sys_dept d ON d.dept_id=c.dept_id WHERE d.dept_name IN (%s,%s,%s) AND d.del_flag='0' AND d.status='0'", COMPANY_NAMES)
            companies = cur.fetchall()
            if len(companies) != 3: raise RuntimeError('Local demo requires exactly the three registered company names')
            companies.sort(key=lambda c: COMPANY_NAMES.index(c['dept_name']))
            planned = rows_for(companies)
            if old and [dict(table=e['table'], key=e['key']) for e in old['rows']] != [dict(table=e['table'], key=e['key']) for e in planned]: raise RuntimeError('Demo plan differs from existing manifest')
            snapshots = []
            known = {(e['table'], json.dumps(e['key'], sort_keys=True)): e for e in old['rows']} if old else {}
            for entry in planned:
                current = select(cur, entry['table'], entry['key'])
                if current:
                    prior = known.get((entry['table'], json.dumps(entry['key'], sort_keys=True)))
                    if not prior or digest(current) != prior['sha256']: raise RuntimeError('Existing ID collision; no overwrite: ' + entry['table'] + str(entry['key']))
                else:
                    values = entry['values'];cur.execute('INSERT INTO `' + entry['table'] + '` (' + ','.join('`' + k + '`' for k in values) + ') VALUES (' + ','.join(['%s'] * len(values)) + ')', list(values.values()))
                    current = select(cur, entry['table'], entry['key'])
                snapshots.append(dict(table=entry['table'], key=entry['key'], sha256=digest(current)))
            manifest = dict(marker=MARK, target=identity, template_ids=[BASE + i * 1000 + 10 for i in range(3)], rows=snapshots)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
        connection.commit()
        return {'action': action, 'rows': len(planned), 'monthly_rows': sum(e['table'] == MONTH_TABLE for e in planned), 'template_ids': manifest['template_ids']}
    except Exception:
        connection.rollback();raise


def main():
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('action', choices=['init', 'verify', 'clean']);p.add_argument('--host', default=os.getenv('MYSQL_HOST', '127.0.0.1'));p.add_argument('--port', type=int, default=int(os.getenv('MYSQL_PORT', '3306')));p.add_argument('--database', default=os.getenv('MYSQL_DATABASE', 'carbon_emissions'));p.add_argument('--user', default=os.getenv('MYSQL_USER', 'root'));p.add_argument('--manifest', default='monthly-analysis-demo-manifest.json');a = p.parse_args()
    if a.host not in ('localhost', '127.0.0.1', '::1'): p.error('This fixture is local-only; production/remote targets are not supported')
    password = os.getenv('MYSQL_PASSWORD') or getpass.getpass('Local MySQL password: ')
    connection = pymysql.connect(host=a.host, port=a.port, user=a.user, password=password, database=a.database, charset='utf8mb4', autocommit=False)
    try: print(json.dumps(run(connection, a.action, a.manifest), ensure_ascii=False))
    finally: connection.close()

if __name__ == '__main__': main()
