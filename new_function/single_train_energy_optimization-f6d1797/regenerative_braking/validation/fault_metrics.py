"""观测异常后的功率恢复指标；阈值是实验统计口径，不是硬件验收值。"""
from __future__ import annotations

import math

import numpy as np


def identifier_phases(diagnostics, *, fault_start_s, fault_end_s):
    """分离启动和故障期间的辨识统计，避免初始 P 掩盖故障峰值。"""
    time=np.asarray(diagnostics["time_s"],dtype=float)
    masks={"pre_fault":time<fault_start_s,
           "fault":(time>=fault_start_s)&(time<fault_end_s),"post_fault":time>=fault_end_s}
    rows=[]
    for phase,mask in masks.items():
        values={key:np.asarray(value,dtype=float)[mask] for key,value in diagnostics.items()}
        innovation=values["normalised_innovation"]
        finite=innovation[np.isfinite(innovation)]
        executed=values["filter_mode"]>=0
        rows.append(dict(phase=phase,updates=int(np.sum(mask)),
            valid_measurements=int(np.sum(values.get("measurement_valid",np.ones(int(np.sum(mask)))))),
            innovation_checks=int(np.sum(values.get("innovation_expected",np.isfinite(innovation)))),
            weight_norm_peak=float(np.max(values["weight_norm"])) if np.any(mask) else None,
            covariance_trace_peak=float(np.max(values["covariance_trace"])) if np.any(mask) else None,
            covariance_min_eigenvalue=float(np.min(values["covariance_min_eigenvalue"])) if np.any(mask) else None,
            innovation_p95=float(np.percentile(finite,95)) if len(finite) else None,
            identifier_updates=int(np.sum(executed)),
            ukf_ratio=float(np.mean(values["filter_mode"][executed])) if np.any(executed) else None,
            switch_count=int(np.sum(values["switched"])),
            max_stale_steps=int(np.max(values["stale_steps"])) if np.any(mask) else None))
    return rows


def power_recovery(times, actual, healthy, *, fault_end_s, dt,
                   mean_window_s=0.05, sustain_s=0.05, relative_tolerance=0.05):
    """故障结束后，向前平均功率持续接近同策略健康运行的首次检测时间。

    只消费故障结束后的样本；恢复时间含平均和连续判定窗口。
    未观测到恢复时返回 None，不将仿真结束误计为恢复。
    """
    times, actual, healthy = (np.asarray(a, dtype=float) for a in (times, actual, healthy))
    scalars = (fault_end_s, dt, mean_window_s, sustain_s, relative_tolerance)
    if not all(math.isfinite(v) for v in scalars) or min(dt, mean_window_s, sustain_s) <= 0 or relative_tolerance < 0:
        raise ValueError("恢复判据参数必须有限，时间窗口必须为正，容差非负")
    if times.ndim != 1 or times.shape != actual.shape or actual.shape != healthy.shape or not len(times):
        raise ValueError("恢复判据需要非空、等长一维时间和功率")
    if not all(np.all(np.isfinite(a)) for a in (times, actual, healthy)) or np.any(np.diff(times) <= 0):
        raise ValueError("恢复数据必须有限且时间严格递增")
    if len(times) > 1 and not np.allclose(np.diff(times), dt, rtol=1e-8, atol=1e-12):
        raise ValueError("恢复时间网格必须与 dt 一致")
    start = int(np.searchsorted(times, fault_end_s-1e-12))
    window = max(1, math.ceil(mean_window_s/dt-1e-12))
    sustain = max(1, math.ceil(sustain_s/dt-1e-12))
    n = len(times)-start
    result = dict(power_recovery_s=None, power_recovery_observed=False,
                  mean_window_s=mean_window_s, sustain_s=sustain_s, relative_tolerance=relative_tolerance)
    if n < window+sustain-1:
        return result
    def average(values):
        cumulative = np.r_[0.0, np.cumsum(values[start:])]
        return (cumulative[window:]-cumulative[:-window])/window
    expected = average(healthy)
    close = np.abs(average(actual)-expected) <= relative_tolerance*np.maximum(np.abs(expected), 1.0)
    cumulative = np.r_[0, np.cumsum(close.astype(int))]
    valid = np.flatnonzero(cumulative[sustain:]-cumulative[:-sustain] == sustain)
    if len(valid):
        detection = start+int(valid[0])+sustain+window-2
        result.update(power_recovery_s=float(times[detection]+dt-fault_end_s), power_recovery_observed=True)
    return result
