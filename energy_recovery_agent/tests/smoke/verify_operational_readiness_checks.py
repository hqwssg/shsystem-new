# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
import json, subprocess, sys
ROOT=Path(__file__).resolve().parents[2]
def main():
    """函数 main：执行该模块中的相关处理逻辑。"""
    out=ROOT/"outputs"/"operational_readiness_smoke"
    p=subprocess.run([sys.executable,str(ROOT/"tools"/"operational_readiness_checks.py"),"--output-dir",str(out)],cwd=ROOT,capture_output=True,text=True)
    if p.returncode: raise AssertionError(p.stdout+p.stderr)
    r=json.loads((out/"operational_readiness_summary.json").read_text(encoding="utf-8")); assert r["passed"] is True,r
    print("operational readiness checks: PASS"); return 0
if __name__=="__main__": raise SystemExit(main())
