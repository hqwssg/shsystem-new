"""复用 regenerative_braking 的阻力口径。"""

from regenerative_braking.dynamics.train_braking_model import (
    BasicResistanceModel,
    total_resistance_n,
)

__all__ = ["BasicResistanceModel", "total_resistance_n"]
