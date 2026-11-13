"""Focused regression for multi-device terminal SOC aggregation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.smoke.verify_heavy_empty_network_optimizer import (
    test_multi_storage_terminal_soc_uses_actual_device_ids,
)


if __name__ == "__main__":
    test_multi_storage_terminal_soc_uses_actual_device_ids()
    print("multi-storage terminal SOC verification: PASS")
