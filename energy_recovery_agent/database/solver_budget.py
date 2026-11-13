"""数据库算法任务的求解资源预算与超时降级策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RESOURCE_PROFILES = ("quick", "standard", "fine")


@dataclass(frozen=True)
class SolveAttempt:
    """一次有界求解尝试及其显式参数覆盖。"""

    name: str
    wall_time_s: int
    parameter_overrides: Mapping[str, Any]
    degraded: bool = False


# 时间限额依据当前合成数据基准设置，正式数据到位后必须重新标定。
_PRIMARY_TIMEOUTS: dict[str, dict[str, int]] = {
    "storage_planning": {"quick": 180, "standard": 600, "fine": 1200},
    "dispatch": {"quick": 480, "standard": 900, "fine": 1200},
    "timetable_audit": {"quick": 120, "standard": 300, "fine": 600},
    "timetable_optimization": {"quick": 180, "standard": 480, "fine": 900},
    "rolling_rescheduling": {"quick": 300, "standard": 600, "fine": 900},
    "joint_parameter_robustness": {"quick": 600, "standard": 1200, "fine": 1800},
}

_FALLBACKS: dict[str, tuple[SolveAttempt, ...]] = {
    "dispatch": (
        SolveAttempt(
            "dispatch_quick_fallback",
            480,
            {"search_profile": "quick", "population_size": 4, "generations": 1},
            True,
        ),
    ),
    "timetable_optimization": (
        SolveAttempt(
            "timetable_rule_fallback",
            180,
            {"mode": "rule", "max_candidates": 60},
            True,
        ),
    ),
    "rolling_rescheduling": (
        SolveAttempt(
            "rolling_minimum_search_fallback",
            300,
            {"population_size": 2, "generations": 1, "max_safety_retries": 0},
            True,
        ),
    ),
}


def build_solve_attempts(
    run_type: str,
    parameters: Mapping[str, Any],
    resource_profile: str = "standard",
) -> tuple[SolveAttempt, ...]:
    """生成主尝试和超时后的有限降级链，不改变原任务数据范围。"""

    if run_type not in _PRIMARY_TIMEOUTS:
        raise ValueError(f"没有为任务类型定义求解资源预算：{run_type}")
    if resource_profile not in RESOURCE_PROFILES:
        raise ValueError(f"未知求解资源档位：{resource_profile}")
    primary = SolveAttempt(
        f"{run_type}_{resource_profile}",
        _PRIMARY_TIMEOUTS[run_type][resource_profile],
        {},
        False,
    )
    fallbacks = []
    for attempt in _FALLBACKS.get(run_type, ()):
        effective = apply_parameter_overrides(parameters, attempt.parameter_overrides)
        if effective != dict(parameters):
            fallbacks.append(attempt)
    return (primary, *fallbacks)


def apply_parameter_overrides(
    parameters: Mapping[str, Any], overrides: Mapping[str, Any]
) -> dict[str, Any]:
    """应用降级覆盖；只允许降低搜索工作量，不改动业务输入。"""

    effective = dict(parameters)
    for name, value in overrides.items():
        if name in {"population_size", "generations", "max_candidates", "max_safety_retries"}:
            current = effective.get(name)
            effective[name] = value if current is None else min(int(current), int(value))
        else:
            effective[name] = value
    return effective


def budget_policy_summary() -> dict[str, Any]:
    """返回供文档、测试和平台部署检查使用的机器可读策略摘要。"""

    return {
        "schema_version": "1.0",
        "resource_profiles": list(RESOURCE_PROFILES),
        "default_profile": "standard",
        "primary_wall_time_s": _PRIMARY_TIMEOUTS,
        "fallbacks": {
            run_type: [
                {
                    "name": item.name,
                    "wall_time_s": item.wall_time_s,
                    "parameter_overrides": dict(item.parameter_overrides),
                }
                for item in attempts
            ]
            for run_type, attempts in _FALLBACKS.items()
        },
        "semantic_guards": {
            "timeout_is_not_infeasible": True,
            "input_scope_reduction_allowed": False,
            "rolling_commit_gate_retained": True,
            "audit_has_no_semantic_fallback": True,
            "joint_robustness_has_no_semantic_fallback": True,
        },
    }
