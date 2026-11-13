import _bootstrap  # noqa: F401
import argparse
import json
from carbon_prediction.pipeline import forecast_all

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--orgs", default="JLG,SNF,YPF")
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--scenario", default="BAU")
    p.add_argument("--as-of", default="2025-12")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args()
    res = forecast_all(horizon=args.horizon, scenario=args.scenario, as_of=args.as_of,
                       org_ids=[x.strip() for x in args.orgs.split(",") if x.strip()],
                       write_db=not args.no_write)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
