"""固定控制网格的剖面细化和成对增益的经验数值敏感性判据。"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from ..simulation.profiles import ProfileSeries


def refine_profile(series: ProfileSeries, dt: float) -> ProfileSeries:
    """零阶保持外生样本：同一输入时序/时长，控制时刻精确取原样本。

    不在不同步长下重新求线路剖面。细网格仅细化平均模型积分，外生速度、
    坡度、功率请求所依赖的剖面样本均在原输入周期内保持。
    """
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError("积分步长必须为正有限值")
    ratio = series.dt / dt
    if not math.isfinite(ratio) or ratio < 1 or not math.isclose(ratio, round(ratio), rel_tol=1e-9):
        raise ValueError("原剖面周期必须是细化积分步长的正整数倍")
    factor = round(ratio)
    if factor == 1:
        return series
    samples = tuple(replace(sample, time_s=sample.time_s + offset * dt)
                    for sample in series.samples for offset in range(factor))
    return replace(series, dt=dt, samples=samples,
        notes=(*series.notes, "外生剖面在原控制网格零阶保持；仅细化物理积分"))


def gain_credibility(rows, *, relative_tolerance=1e-3, absolute_floor_kwh=1e-5):
    """由每个 h 的同对象原/候选能量配对，报告经验敏感性而非统计置信区间。

    先检查物理/闭合门禁，再检查最细两档能量差。正增益必须覆盖全部步长，
    且最小增益大于增益跨度加绝对下限。阈值须在运行前声明。
    """
    if not all(math.isfinite(v) and v >= 0 for v in (relative_tolerance, absolute_floor_kwh)):
        raise ValueError("数值可信度阈值必须为非负有限值")
    groups = {}
    for row in rows:
        key = float(row["dt"])
        group = groups.setdefault(key, {})
        if row["candidate"] in group:
            raise ValueError("重复的积分步长/候选结果")
        group[row["candidate"]] = row
    if len(groups) < 3 or any(set(group) != {"legacy", "current_feedback"} for group in groups.values()):
        raise ValueError("可信度判据要求至少三档步长，每档各一个原/候选结果")
    dts = sorted(groups)
    field = "storage_net_of_grid_import_energy_kWh"
    energies = np.array([[float(groups[dt][candidate][field]) for candidate in ("legacy", "current_feedback")]
                         for dt in dts])
    if not np.all(np.isfinite(energies)):
        raise ValueError("能量含非有限值")
    gains = energies[:, 1] - energies[:, 0]
    margin = float(np.ptp(gains))
    fine_relative_change = float(np.max(np.abs(energies[0] - energies[1]) / np.maximum(np.abs(energies[0]), 1e-9)))
    feasible = all(not row["physical_violation"] and not row["closure_failure"] for row in rows)
    resolved = fine_relative_change <= relative_tolerance
    credible = feasible and resolved and float(np.min(gains)) > margin + absolute_floor_kwh
    return dict(status="supported" if credible else "unresolved", feasible=feasible,
        finest_energy_relative_change=fine_relative_change, finest_energy_resolved=resolved,
        min_gain_kWh=float(np.min(gains)), max_gain_kWh=float(np.max(gains)),
        gain_spread_kWh=margin, finest_gain_kWh=float(gains[0]),
        relative_tolerance=relative_tolerance, absolute_floor_kWh=absolute_floor_kwh,
        note="经验步长敏感性筛查，不是严格误差上界、统计置信区间或全局最优证明")
