import _bootstrap  # noqa: F401
import json
from carbon_prediction.reporting import generate_all

if __name__ == "__main__":
    print(json.dumps(generate_all(), ensure_ascii=False, indent=2))
