# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
import subprocess, sys, time, json
root = Path('.').resolve()
tests = sorted((root / 'tests' / 'smoke').glob('verify_*.py'))
print('found', len(tests), 'smoke tests', flush=True)
results = []
t_all = time.time()
for p in tests:
    t0 = time.time()
    print('RUN', p.name, flush=True)
    proc = subprocess.run([sys.executable, str(p)], cwd=str(root), capture_output=True, text=True)
    dt = time.time() - t0
    results.append({
        'test': p.name,
        'returncode': proc.returncode,
        'seconds': round(dt, 2),
        'stdout_tail': (proc.stdout or '')[-500:],
        'stderr_tail': (proc.stderr or '')[-800:],
    })
    status = 'PASS' if proc.returncode == 0 else 'FAIL'
    print(f'  -> {status} ({dt:.1f}s)', flush=True)
    if proc.returncode != 0:
        print(((proc.stderr or proc.stdout or '')[-400:]), flush=True)
summary = {
    'total': len(results),
    'passed': sum(1 for r in results if r['returncode'] == 0),
    'failed': sum(1 for r in results if r['returncode'] != 0),
    'seconds': round(time.time() - t_all, 2),
    'results': results,
}
out = root / 'outputs' / 'smoke_rerun_report.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('SUMMARY', summary['passed'], '/', summary['total'], 'in', summary['seconds'], 's', flush=True)
print('report', out, flush=True)
raise SystemExit(1 if summary['failed'] else 0)
