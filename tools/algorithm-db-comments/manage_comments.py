"""Plan/apply/revert COMMENT-only changes using the target MySQL SHOW CREATE definitions."""
from __future__ import annotations

import argparse
import datetime
import getpass
import hashlib
import json
from pathlib import Path
import re
import sys

TOKEN = re.compile(r"'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\"|`(?:``|[^`])*`|[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:\.[0-9]+)?|[^\s]", re.S)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def comment_spans(text):
    tokens = list(TOKEN.finditer(text)); result = []
    for i, token in enumerate(tokens):
        if token.group().upper() != 'COMMENT':
            continue
        j = i + 1
        if j < len(tokens) and tokens[j].group() == '=':
            j += 1
        if j >= len(tokens) or tokens[j].group()[0] not in "'\"":
            raise ValueError('Cannot parse COMMENT clause; no changes made')
        result.append((token.start(), tokens[j].end()))
    return result


def _without_comments(ddl):
    # Ignore only COMMENT literals and the mutable next AUTO_INCREMENT value.
    for start, end in reversed(comment_spans(ddl)):
        ddl = ddl[:start] + ddl[end:]
    return ddl


def _token_structure_hash(ddl):
    tokens = [m.group() for m in TOKEN.finditer(ddl)]; out = []; i = 0
    while i < len(tokens):
        if tokens[i].upper() == 'AUTO_INCREMENT' and tokens[i+1:i+2] == ['=']:
            i += 3
        else:
            token = tokens[i]
            # MySQL reserializes legacy CHECK string introducers on metadata ALTER.
            # These two charsets encode the same ASCII constants (heavy/empty etc.).
            # Non-ASCII, binary literals, explicit collations and expressions remain strict.
            if token.lower() in ('_gbk', '_utf8mb4') and i+1 < len(tokens):
                literal = tokens[i+1]
                if literal.startswith("'") and literal.isascii():
                    token = '_ascii_compatible'
            out.append(token); i += 1
    return digest(out)


def legacy_structure_hash(ddl):
    """Hash format used by plans created before inherited charset normalization."""
    return _token_structure_hash(_without_comments(ddl))


def legacy_charset_compatible_hash(ddl):
    """Match legacy plans when MySQL expands only the inherited column charset."""
    ddl = _without_comments(ddl)
    table_charset = re.search(r'\bDEFAULT\s+CHARSET\s*=\s*([A-Za-z0-9_]+)', ddl, re.I)
    if table_charset:
        charset = table_charset.group(1)
        lines = []
        for line in ddl.splitlines():
            if re.match(r'^\s*`(?:``|[^`])+`\s+', line):
                line = re.sub(
                    r'\s+CHARACTER\s+SET\s+' + re.escape(charset) + r'(?=\s|,|$)',
                    '', line, flags=re.I,
                )
            lines.append(line)
        ddl = '\n'.join(lines)
    # Keep COLLATE tokens intact: the saved legacy plan hash includes them.
    return _token_structure_hash(ddl)


def structure_hash(ddl):
    ddl = _without_comments(ddl)
    # MySQL may expand inherited table charset/collation onto column lines after ALTER.
    # Remove only attributes that exactly match the table defaults.
    table_charset = re.search(r'\bDEFAULT\s+CHARSET\s*=\s*([A-Za-z0-9_]+)', ddl, re.I)
    table_collation = re.search(r'\b(?:DEFAULT\s+)?COLLATE\s*=\s*([A-Za-z0-9_]+)', ddl, re.I)
    if table_charset and table_collation:
        charset, collation = table_charset.group(1), table_collation.group(1)
        lines = []
        for line in ddl.splitlines():
            if re.match(r'^\s*`(?:``|[^`])+`\s+', line):
                line = re.sub(
                    r'\s+CHARACTER\s+SET\s+' + re.escape(charset) + r'(?=\s|,|$)',
                    '', line, flags=re.I,
                )
                line = re.sub(
                    r'\s+COLLATE\s+' + re.escape(collation) + r'(?=\s|,|$)',
                    '', line, flags=re.I,
                )
            lines.append(line)
        ddl = '\n'.join(lines)
    return _token_structure_hash(ddl)


def quote_identifier(name):
    return '`' + name.replace('`', '``') + '`'


def quote_comment(value, sql_mode):
    if 'NO_BACKSLASH_ESCAPES' not in sql_mode.split(','):
        value = value.replace('\\', '\\\\').replace('\0', '\\0').replace('\n', '\\n').replace('\r', '\\r')
    return "'" + value.replace("'", "''") + "'"


def column_definitions(ddl):
    result = {}
    for line in ddl.splitlines():
        match = re.match(r'^\s*`((?:``|[^`])+)`\s+', line)
        if match:
            definition = line.strip()
            if definition.endswith(','):
                definition = definition[:-1]
            result[match[1].replace('``', '`')] = definition
    return result


def replace_comment(definition, value, sql_mode):
    spans = comment_spans(definition)
    if len(spans) > 1:
        raise ValueError('Multiple column COMMENT clauses; no changes made')
    clause = 'COMMENT ' + quote_comment(value, sql_mode)
    if spans:
        start, end = spans[0]
        return definition[:start] + clause + definition[end:]
    return definition + ' ' + clause


def query(connection, sql, args=None):
    import pymysql
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql, args)
        return cursor.fetchall()


def inspect(connection, table):
    row = query(connection, 'SHOW CREATE TABLE ' + quote_identifier(table))[0]
    ddl = row['Create Table']
    columns = query(connection, 'SHOW FULL COLUMNS FROM ' + quote_identifier(table))
    definitions = column_definitions(ddl)
    if set(definitions) != {r['Field'] for r in columns}:
        raise ValueError('Unsupported multiline column definition: ' + table)
    info = query(connection, 'SELECT TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND TABLE_TYPE=%s', (table, 'BASE TABLE'))
    if len(info) != 1:
        raise ValueError('Not an existing base table: ' + table)
    return {'ddl': ddl, 'structure_sha256': structure_hash(ddl),
            'legacy_structure_sha256': legacy_structure_hash(ddl),
            'legacy_charset_compatible_sha256': legacy_charset_compatible_hash(ddl),
            'definitions': definitions,
            'comments': {'table': info[0]['TABLE_COMMENT'], 'columns': {r['Field']: r['Comment'] for r in columns}}}


def server_identity(connection):
    return query(connection, 'SELECT DATABASE() AS database_name,@@server_uuid AS server_uuid,@@version AS mysql_version,@@sql_mode AS sql_mode')[0]


def data_fingerprint(connection, table):
    import pymysql
    columns = query(connection, 'SHOW FULL COLUMNS FROM ' + quote_identifier(table))
    keys = query(connection, 'SHOW INDEX FROM ' + quote_identifier(table) + " WHERE Key_name='PRIMARY'")
    if not keys:
        raise ValueError('Data verification requires a primary key: ' + table)
    order = ','.join(quote_identifier(r['Column_name']) for r in sorted(keys, key=lambda r: r['Seq_in_index']))
    select = ','.join(quote_identifier(r['Field']) for r in columns)
    h = hashlib.sha256(); count = 0
    with connection.cursor(pymysql.cursors.SSCursor) as cursor:
        cursor.execute('SELECT ' + select + ' FROM ' + quote_identifier(table) + ' ORDER BY ' + order)
        for row in cursor:
            count += 1
            for value in row:
                if value is None:
                    data = b'N'
                elif isinstance(value, bytes):
                    data = b'B' + value
                elif isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
                    data = b'T' + value.isoformat().encode()
                else:
                    data = (type(value).__name__ + ':' + str(value)).encode('utf8')
                h.update(len(data).to_bytes(8, 'big')); h.update(data)
    return {'rows': count, 'sha256': h.hexdigest()}


def alter_sql(table, live, desired, sql_mode):
    clauses = []
    for field, value in desired['columns'].items():
        if live['comments']['columns'][field] != value:
            clauses.append('MODIFY COLUMN ' + replace_comment(live['definitions'][field], value, sql_mode))
    if live['comments']['table'] != desired['table']:
        clauses.append('COMMENT=' + quote_comment(desired['table'], sql_mode))
    if not clauses:
        return None
    return 'ALTER TABLE ' + quote_identifier(table) + '\n  ' + ',\n  '.join(clauses) + ',\n  ALGORITHM=INPLACE, LOCK=NONE'


def load_catalog(path):
    catalog = json.loads(Path(path).read_text('utf8'))
    for table, spec in catalog['tables'].items():
        if not re.fullmatch(r'(?:energy_|single_)[a-z0-9_]+', table):
            raise ValueError('Invalid scope: ' + table)
        for text in [spec['comment'], *spec['columns'].values()]:
            if not text or len(text.encode('utf8')) > 1024:
                raise ValueError('Empty or oversized comment: ' + table)
    return catalog


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def plan(connection, catalog, folder, check_data=False):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    identity = server_identity(connection)
    present = {r['TABLE_NAME'] for r in query(connection, 'SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE=%s', ('BASE TABLE',))}
    result = {'identity': identity, 'catalog_sha256': digest(catalog), 'check_data': check_data, 'tables': {}, 'missing_tables': [], 'missing_columns': {}, 'unknown_columns_kept': {}}
    forward = ['-- Review only. Use the apply command for identity, drift and structure checks.', 'SET NAMES utf8mb4;']
    backward = ['-- COMMENT-only rollback for this target plan; never recreates tables.', 'SET NAMES utf8mb4;']
    originals = []
    for table, spec in catalog['tables'].items():
        if table not in present:
            result['missing_tables'].append(table); continue
        live = inspect(connection, table); after = json.loads(json.dumps(live['comments']))
        result['missing_columns'][table] = sorted(set(spec['columns']) - set(after['columns']))
        result['unknown_columns_kept'][table] = sorted(set(after['columns']) - set(spec['columns']))
        after['table'] = spec['comment']
        after['columns'].update({c: text for c, text in spec['columns'].items() if c in after['columns']})
        entry = {'before_structure_sha256': live['structure_sha256'], 'before_comments': live['comments'], 'after_comments': after}
        if check_data:
            entry['before_data'] = data_fingerprint(connection, table)
        result['tables'][table] = entry
        statement = alter_sql(table, live, after, identity['sql_mode'])
        if statement:
            forward.append(statement + ';')
            rollback_live = {**live, 'comments': after}
            # Rebuild the rollback definitions with the current desired comments before replacing them.
            rollback_live['definitions'] = {c: replace_comment(d, after['columns'][c], identity['sql_mode']) for c, d in live['definitions'].items()}
            backward.append(alter_sql(table, rollback_live, live['comments'], identity['sql_mode']) + ';')
        originals.append('-- Original structure for review; do not execute as a restore.\n' + live['ddl'] + ';')
    if not result['tables']:
        raise ValueError('No algorithm tables found; check the database name')
    write_json(folder/'plan.json', result)
    (folder/'apply.sql').write_text('\n\n'.join(forward) + '\n', encoding='utf8')
    (folder/'rollback.sql').write_text('\n\n'.join(backward) + '\n', encoding='utf8')
    (folder/'before-schema.sql').write_text('\n\n'.join(originals) + '\n', encoding='utf8')
    return result


def apply(connection, catalog, folder, rollback=False):
    folder = Path(folder); saved = json.loads((folder/'plan.json').read_text('utf8')); identity = server_identity(connection)
    for key in ('database_name', 'server_uuid', 'sql_mode'):
        if identity[key] != saved['identity'][key]:
            raise ValueError('Target identity or SQL mode differs from this plan: ' + key)
    if digest(catalog) != saved['catalog_sha256']:
        raise ValueError('Comment catalog differs; use the catalog that created this plan')
    lock = 'algorithm_comments_' + digest(identity['database_name'])[:30]
    if query(connection, 'SELECT GET_LOCK(%s,0) AS locked', (lock,))[0]['locked'] != 1:
        raise RuntimeError('Another comment operation is in progress')
    completed = []; data_before = {}; ddl_changes = []; mysql_copy_tables = []
    try:
        # Validate the whole plan before the first ALTER; SQL is rebuilt from live definitions.
        for table, entry in saved['tables'].items():
            if table not in catalog['tables']:
                raise ValueError('Table outside catalog: ' + table)
            live = inspect(connection, table)
            expected_hash = entry['before_structure_sha256']
            if expected_hash not in (live['structure_sha256'], live['legacy_structure_sha256'], live['legacy_charset_compatible_sha256']):
                raise ValueError('Schema drift detected before any DDL: ' + table)
            if live['comments'] not in (entry['before_comments'], entry['after_comments']):
                raise ValueError('Comments were edited after this plan: ' + table)
            wanted = entry['before_comments'] if rollback else entry['after_comments']
            statement = alter_sql(table, live, wanted, identity['sql_mode'])
            if statement:
                ddl_changes.append((table, statement, wanted))
                if saved['check_data']:
                    data_before[table] = data_fingerprint(connection, table)
                    if not rollback and data_before[table] != entry['before_data']:
                        raise ValueError('Rows changed after plan; generate a fresh plan during a quiet period: ' + table)
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION lock_wait_timeout=15')
        for table, statement, wanted in ddl_changes:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(statement)
                except Exception as error:
                    # Certain MySQL 8.0 CHECK combinations require its internal copy
                    # algorithm even for COMMENT-only MODIFY. Never drop constraints.
                    if not error.args or error.args[0] not in (1845, 1846):
                        raise
                    if not saved['check_data']:
                        raise RuntimeError('MySQL requires its internal COPY algorithm; regenerate the plan with --check-data in a maintenance window') from error
                    cursor.execute(statement.replace('ALGORITHM=INPLACE, LOCK=NONE', 'ALGORITHM=COPY, LOCK=SHARED'))
                    mysql_copy_tables.append(table)
            completed.append(table)
            live = inspect(connection, table)
            expected_hash = saved['tables'][table]['before_structure_sha256']
            if expected_hash not in (live['structure_sha256'], live['legacy_structure_sha256'], live['legacy_charset_compatible_sha256']):
                raise RuntimeError('Post-DDL structure verification failed: ' + table)
            if live['comments'] != wanted:
                raise RuntimeError('Post-DDL structure or comment verification failed: ' + table)
        for table, before in data_before.items():
            if data_fingerprint(connection, table) != before:
                raise RuntimeError('Data changed during comment operation: ' + table)
        result = {'action': 'rollback' if rollback else 'apply', 'changed_tables': completed, 'planned_tables': len(saved['tables']), 'mysql_internal_copy_tables': mysql_copy_tables, 'data_verified_tables': len(data_before), 'structure_verified': True, 'success': True}
        write_json(folder/('rollback-result.json' if rollback else 'apply-result.json'), result)
        return result
    except BaseException as error:
        # MySQL ALTER implicitly commits: do not claim transaction-wide rollback.
        write_json(folder/'last-error.json', {'action': 'rollback' if rollback else 'apply', 'completed_tables': completed, 'error': str(error), 'ddl_is_not_transactional': True})
        raise
    finally:
        query(connection, 'SELECT RELEASE_LOCK(%s)', (lock,))


def verify(connection, catalog):
    present = {r['TABLE_NAME'] for r in query(connection, 'SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()', ())}
    mismatches = []; tables = 0; columns = 0; missing_columns = {}; unknown_columns = {}
    for table, spec in catalog['tables'].items():
        if table not in present:
            continue
        live = inspect(connection, table); tables += 1
        absent = sorted(set(spec['columns']) - set(live['comments']['columns']))
        extra = sorted(set(live['comments']['columns']) - set(spec['columns']))
        if absent:
            missing_columns[table] = absent
        if extra:
            unknown_columns[table] = extra
        if live['comments']['table'] != spec['comment']:
            mismatches.append(table + ' [table comment]')
        for c, text in spec['columns'].items():
            if c in live['comments']['columns']:
                columns += 1
                if live['comments']['columns'][c] != text:
                    mismatches.append(table + '.' + c)
    if not tables:
        raise ValueError('No algorithm tables found; check the database name')
    missing = sorted(set(catalog['tables']) - present)
    return {'tables': tables, 'columns': columns, 'missing_tables_skipped': missing, 'missing_columns_skipped': missing_columns, 'unknown_columns_kept': unknown_columns, 'mismatches': mismatches, 'success': not mismatches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'apply', 'rollback', 'verify'))
    parser.add_argument('--host', default='127.0.0.1'); parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--user', default='root'); parser.add_argument('--database', required=True)
    parser.add_argument('--catalog', type=Path, default=Path(__file__).with_name('comments.json'))
    parser.add_argument('--output', type=Path); parser.add_argument('--plan', type=Path); parser.add_argument('--check-data', action='store_true')
    args = parser.parse_args()
    if args.action == 'plan' and not args.output:
        parser.error('plan requires --output (a new directory)')
    if args.action in ('apply', 'rollback') and not args.plan:
        parser.error('apply/rollback requires --plan')
    import pymysql
    catalog = load_catalog(args.catalog)
    connection = pymysql.connect(host=args.host, port=args.port, user=args.user, password=getpass.getpass('MySQL password: '), database=args.database, charset='utf8mb4', autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION time_zone='+00:00'")
        if args.action == 'plan':
            result = plan(connection, catalog, args.output, args.check_data)
            print(json.dumps({'planned_tables': len(result['tables']), 'missing_tables_skipped': result['missing_tables'], 'output': str(args.output)}, ensure_ascii=False))
        elif args.action == 'verify':
            result = verify(connection, catalog); print(json.dumps(result, ensure_ascii=False)); return 0 if result['success'] else 1
        else:
            print(json.dumps(apply(connection, catalog, args.plan, args.action == 'rollback'), ensure_ascii=False))
    finally:
        connection.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr); raise SystemExit(1)
