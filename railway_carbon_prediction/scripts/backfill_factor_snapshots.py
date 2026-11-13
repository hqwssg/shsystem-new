"""回填历史排放结果的因子版本与快照。

适用场景：已按 003_factor_snapshot.sql 增加列，但历史 252 条结果还没有
factor_snapshot。脚本按 org×period 重新解析因子并重算，写入快照。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from carbon_prediction import db, pipeline  # noqa: E402


def main() -> None:
    rows = db.fetch_all(
        "SELECT DISTINCT org_id, period FROM prediction_emission_monthly "
        "ORDER BY org_id, period"
    )
    ok = 0
    failed = []
    for r in rows:
        try:
            pipeline._recompute_emission(
                r["org_id"], r["period"], batch_id="BACKFILL-FACTOR"
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed.append((r["org_id"], str(r["period"]), str(exc)))
    print(f"backfilled={ok} failed={len(failed)}")
    for item in failed[:20]:
        print("FAIL", *item)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
