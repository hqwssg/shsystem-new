import _bootstrap  # noqa: F401
import argparse
import json
from carbon_prediction.config import settings
from carbon_prediction.db import execute_script
from carbon_prediction.pipeline import (forecast_all, import_history, run_anomaly_scan,
                                         train_all)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--skip-init", action="store_true")
    p.add_argument("--skip-import", action="store_true")
    p.add_argument("--skip-anomaly", action="store_true")
    p.add_argument("--skip-train", action="store_true")
    p.add_argument("--skip-forecast", action="store_true")
    p.add_argument("--as-of", default="2025-12")
    args = p.parse_args()

    if not args.skip_init:
        execute_script(str(settings.sql_dir / "001_schema.sql"))
        execute_script(str(settings.sql_dir / "002_seed.sql"))
        print("[1/5] 数据库结构/种子完成")
    if not args.skip_import:
        print("[2/5] 历史导入:", json.dumps(import_history(), ensure_ascii=False))
    if not args.skip_anomaly:
        print("[3/5] 异常筛查:", json.dumps(run_anomaly_scan(), ensure_ascii=False, default=str))
    if not args.skip_train:
        res = train_all(mode="full", as_of=args.as_of)
        print("[4/5] 训练完成:", {k: v.get("model_id") for k, v in res["results"].items()})
    if not args.skip_forecast:
        res = forecast_all(horizon=12, scenario="BAU", as_of=args.as_of, write_db=True)
        print("[5/5] 预测完成:", {r["org_id"]: r["total_comparable"] for r in res["results"]})
