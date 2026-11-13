"""Platform adapter; the research algorithm is loaded without modifying it."""
from pathlib import Path
import os
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
def _configured_path(name, candidates):
    configured = os.environ.get(name)
    paths = [Path(configured)] if configured else []
    paths.extend(Path(item) for item in candidates)
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved.exists():
            return resolved
    return paths[0].expanduser().resolve()


ALGORITHM = _configured_path('SINGLE_TRAIN_ALGORITHM_ROOT', (
    WORKSPACE / 'single_train_algorithm',
    WORKSPACE / 'new_function/single_train_energy_optimization-f6d1797',
))
if not (ALGORITHM / 'regenerative_braking').is_dir():
    raise RuntimeError('找不到单列车算法，请配置 SINGLE_TRAIN_ALGORITHM_ROOT')
sys.path.insert(0, str(ALGORITHM))

HEAVY_ROOT = _configured_path('SINGLE_TRAIN_HEAVY_ROOT', (
    WORKSPACE / 'energy-engine',
    WORKSPACE / 'energy_recovery_agent',
))
if not (HEAVY_ROOT / 'database/mysql.py').is_file():
    raise RuntimeError('找不到重空协同数据适配依赖，请配置 SINGLE_TRAIN_HEAVY_ROOT')
sys.path.insert(0, str(HEAVY_ROOT))
