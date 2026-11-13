"""节能候选排序：硬门禁先行，能量优先，抖振只作末级判据。"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

ENERGY_OBJECTIVES = ("captured_energy_kWh", "storage_energy_kWh", "storage_net_of_grid_import_energy_kWh")
DEFAULT_ENERGY_OBJECTIVE = "storage_net_of_grid_import_energy_kWh"
SELECTION_RULE = (
    "先要求物理越限和闭合失败均为零；"
    "优先最大化目标总能量，再比较最差场景的目标能量与机械制动能量之比；"
    "随后最小化占空比总变差，完全相同时按候选名称排序"
)


def summarize_candidate(
    rows: Sequence[Mapping[str, Any]], *, objective: str = DEFAULT_ENERGY_OBJECTIVE,
    closure_tolerance: float = 1.0e-4,
) -> dict[str, Any]:
    if not rows or objective not in ENERGY_OBJECTIVES:
        raise ValueError("候选结果不能为空且目标必须为已声明的能量指标")
    if not math.isfinite(closure_tolerance) or closure_tolerance <= 0.0:
        raise ValueError("闭合容差必须为正有限值")
    energies, ratios, variations = [], [], []
    closures = []
    for row in rows:
        energy = float(row[objective])
        mechanical = float(row["mechanical_braking_energy_kWh"])
        closure = abs(float(row["closure_relative_residual"]))
        tv = float(row["control_effort_tv"])
        if not all(math.isfinite(value) for value in (energy, mechanical, closure, tv)):
            raise ValueError("候选统计含非有限值")
        if mechanical < 0.0 or tv < 0.0:
            raise ValueError("机械制动能量与控制总变差不能为负")
        if mechanical == 0.0 and energy != 0.0:
            raise ValueError("零制动能量场景不能用于非零回收量的比例排序")
        energies.append(energy)
        ratios.append(energy / mechanical if mechanical else 0.0)
        closures.append(closure)
        variations.append(tv)
    physical = sum(bool(row["physical_violation"]) for row in rows)
    failures = sum(value > closure_tolerance for value in closures)
    return {
        "case_count": len(rows), "physical_violation_count": physical,
        "closure_failure_count": failures, "fully_feasible": physical == failures == 0,
        "energy_objective": objective, "total_objective_energy_kWh": math.fsum(energies),
        "min_objective_ratio": min(ratios), "mean_objective_ratio": math.fsum(ratios) / len(rows),
        "sum_control_effort_tv": math.fsum(variations),
        "max_closure_relative_residual": max(closures),
    }


def candidate_rank(summary: Mapping[str, Any], name: str = "") -> tuple:
    """门禁失败者仅供诊断排序，不可作为通过门禁的推荐候选。"""
    return (
        summary["physical_violation_count"], summary["closure_failure_count"],
        -summary["total_objective_energy_kWh"], -summary["min_objective_ratio"],
        summary["sum_control_effort_tv"], name,
    )


def select_candidate(summaries: Mapping[str, Mapping[str, Any]]) -> str | None:
    feasible = [name for name, item in summaries.items() if item["fully_feasible"]]
    return min(feasible, key=lambda name: candidate_rank(summaries[name], name)) if feasible else None
