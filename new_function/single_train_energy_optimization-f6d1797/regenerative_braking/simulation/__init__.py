"""仿真子包：工况剖面、控制器接口、闭环仿真器。

.. note::
   ``closed_loop`` 的符号**延迟导入**（PEP 562），不用模块级 ``from .closed_loop import``。

   原因是一条真实的循环导入：``control/nsmc.py`` 需要 ``simulation.controllers``，
   而导入 ``simulation.controllers`` 会先执行本 ``__init__``；若本 ``__init__``
   再急切导入 ``closed_loop``，而 ``closed_loop`` 又要 ``control.nsmc``，
   此时 ``control.nsmc`` 只加载了一半 → ``ImportError: partially initialized module``。

   该缺陷只在**先导入 ``regenerative_braking.control.nsmc``**（例如
   ``pytest tests/test_nsmc.py``）时暴露；全量测试因为先导入了 ``simulation``
   而被掩盖。延迟导入把这条边去掉，两种导入顺序都能工作。
"""

from importlib import import_module
from typing import Any

from .controllers import (
    ControllerCommand,
    ControllerError,
    ControllerObservation,
    FixedDutyController,
    PIController,
    PIDController,
    RegenController,
    TraditionalSMCController,
    ZeroDutyController,
    ideal_buck_duty_for_power,
)
from .profiles import (
    ProfileError,
    ProfileSeries,
    constant_deceleration_series,
    grade_hold_series,
    long_downhill_ranges_from_shared,
    route_braking_series,
    segmented_braking_series,
)
from .regenerative_simulator import (
    RegenerativeBrakingSimulator,
    SimulationArrays,
    SimulationConfig,
    SimulationError,
    SimulationResult,
)

#: 延迟导入的符号 → 所属子模块（见模块 docstring 的循环导入说明）
_LAZY_EXPORTS = {
    "CLOSED_LOOP_PENDING_ITEMS": ".closed_loop",
    "ClosedLoopController": ".closed_loop",
    "ClosedLoopError": ".closed_loop",
    "PendingSchemeItem": ".closed_loop",
    "build_closed_loop_controller": ".closed_loop",
}


def __getattr__(name: str) -> Any:
    """按需导入 ``closed_loop`` 的符号（PEP 562）。"""

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "CLOSED_LOOP_PENDING_ITEMS",
    "ClosedLoopController",
    "ClosedLoopError",
    "ControllerCommand",
    "ControllerError",
    "ControllerObservation",
    "FixedDutyController",
    "PIController",
    "PIDController",
    "PendingSchemeItem",
    "ProfileError",
    "ProfileSeries",
    "RegenController",
    "TraditionalSMCController",
    "RegenerativeBrakingSimulator",
    "SimulationArrays",
    "SimulationConfig",
    "SimulationError",
    "SimulationResult",
    "ZeroDutyController",
    "build_closed_loop_controller",
    "constant_deceleration_series",
    "grade_hold_series",
    "ideal_buck_duty_for_power",
    "long_downhill_ranges_from_shared",
    "route_braking_series",
    "segmented_braking_series",
]
