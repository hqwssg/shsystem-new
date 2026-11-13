import _bootstrap  # noqa: F401
import argparse
import json
from carbon_prediction.config import settings
from carbon_prediction.pipeline import train_all

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--orgs", default="JLG,SNF,YPF")
    p.add_argument("--mode", default="full", choices=["auto", "full", "finetune"])
    p.add_argument("--as-of", default="2025-12")
    args = p.parse_args()
    res = train_all(mode=args.mode, as_of=args.as_of,
                    org_ids=[x.strip() for x in args.orgs.split(",") if x.strip()])
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
