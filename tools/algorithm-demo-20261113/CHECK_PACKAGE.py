"""Read-only verification; no database connection or initialization."""
from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parent
for line in (root/'SHA256SUMS').read_text('utf8').splitlines():
    expected,name=line.split('  ',1)
    file=(root/name).resolve()
    if not file.is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Checksum mismatch: '+name)
shell=(root/'init_algorithm_demo.sh').read_text('utf8')
sql=(root/'init_algorithm_demo.sql').read_text('utf8')
embedded=shell.split("<<'__ALG_SQL__'\n",1)[1].split('\n__ALG_SQL__',1)[0]+'\n'
if embedded!=sql:
    raise SystemExit('Shell embedded SQL differs from standalone SQL')
manifest=json.loads((root/'data-manifest.json').read_text('utf8'))
assert len(manifest['heavyVersions'])==1 and manifest['noTasksOrResults'] is True
assert 'eco_driving' in manifest['singleTaskTypes']
print('ALGORITHM_DEMO_PACKAGE_OK: checksums, embedded SQL and manifest verified; no database accessed')
