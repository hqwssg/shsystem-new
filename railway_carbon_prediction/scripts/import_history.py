import _bootstrap  # noqa: F401
import json
from carbon_prediction.pipeline import import_history

if __name__ == "__main__":
    print(json.dumps(import_history(), ensure_ascii=False, indent=2))
