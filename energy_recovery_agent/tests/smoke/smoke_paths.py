"""Shared output paths for smoke checks.

Direct execution retains the historical ``outputs/`` location. The unified
entry point injects ``HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT`` to isolate successful
smoke artifacts in a temporary directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def smoke_output(*parts: str) -> Path:
    """函数 smoke_output：执行该模块中的相关处理逻辑。"""
    root = Path(os.environ.get("HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT", "outputs"))
    return root.joinpath(*parts)
