import _bootstrap  # noqa: F401
import json
from carbon_prediction.pipeline import run_anomaly_scan

if __name__ == "__main__":
    print(json.dumps(run_anomaly_scan(), ensure_ascii=False, indent=2, default=str))
