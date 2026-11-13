"""电气传感器有色噪声、偏置、延迟、丢样；所有故障均为明确标注的仿真假设。"""
from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, replace

import numpy as np

CHANNELS = ("input_voltage_v", "output_voltage_v", "inductor_current_a", "output_current_a")


@dataclass(frozen=True)
class ObservationFault:
    start_s: float = 1.0
    end_s: float = 2.0
    relative_std: float = 0.0
    correlation: float = 0.0
    voltage_bias_fraction: float = 0.0
    current_bias_fraction: float = 0.0
    delay_steps: int = 0
    dropout_probability: float = 0.0
    outage_steps: int = 0
    seed: int = 20261008
    data_status: str = "assumed"

    def __post_init__(self):
        scalars = (self.start_s,self.end_s,self.relative_std,self.correlation,
                   self.voltage_bias_fraction,self.current_bias_fraction,self.dropout_probability)
        if not all(np.isfinite(v) for v in scalars) or not 0 <= self.start_s < self.end_s:
            raise ValueError("故障时窗/参数必须有限，且 0<=start<end")
        if self.relative_std < 0 or not abs(self.correlation) < 1 or not 0 <= self.dropout_probability <= 1:
            raise ValueError("噪声幅值、AR(1) 相关系数或丢样概率不合法")
        if any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in (self.delay_steps,self.outage_steps)):
            raise ValueError("延迟/连续丢样长度必须为非负整数")
        if isinstance(self.seed,bool) or not isinstance(self.seed,int) or self.seed<0:
            raise ValueError("种子必须为非负整数")
        if self.data_status not in ("assumed","synthetic"):
            raise ValueError("注入故障必须标为 assumed 或 synthetic")


class FaultObservationController:
    """只污染四个电气量；当前时间、功率请求、SOC、BMS 许可保持当前拍。

    丢样时保持最后有效电气量，明确记录 stale_steps，仍让控制器按 Ts 更新；
    safe_exit 将采集缺测标志交给主算法；hold 保留修复前耐受对照。
    标志来自采集接口/故障注入，不宣称控制器可诊断未标记的偏置或延迟。
    """
    def __init__(self, inner, fault, *, missing_policy="safe_exit"):
        if missing_policy not in ("safe_exit", "hold"):
            raise ValueError("missing_policy 必须为 safe_exit 或 hold")
        self.inner,self.fault,self.missing_policy=inner,fault,missing_policy
        self.reset()

    @property
    def name(self):
        return self.inner.name+"+observation_fault"

    @property
    def sample_time_s(self):
        return getattr(self.inner,"sample_time_s",None)

    def reset(self):
        self.inner.reset()
        self.rng=np.random.default_rng(self.fault.seed)
        self.colored=self.rng.standard_normal(4)
        self.buffer=deque(maxlen=self.fault.delay_steps+1)
        self.last_valid=None
        self.stale_steps=0
        self.active_index=0
        self.update_count=0
        self.dropout_count=0
        self.innovation_digest=hashlib.sha256()
        self.diagnostics={key:[] for key in ("time_s","stale_steps","weight_norm","covariance_trace",
            "covariance_min_eigenvalue","normalised_innovation","filter_mode","switched",
            "measurement_valid","innovation_expected")}

    def accept_applied_command(self, command):
        notify=getattr(self.inner,"accept_applied_command",None)
        if notify is not None:
            notify(command)

    def perturb(self, observation):
        values=np.array([getattr(observation,key) for key in CHANNELS],dtype=float)
        self.buffer.append(values)
        f=self.fault
        active=f.start_s <= observation.time_s < f.end_s
        innovation=self.rng.standard_normal(4)
        drop_draw=self.rng.random()
        self.innovation_digest.update(innovation.tobytes())
        self.innovation_digest.update(np.float64(drop_draw).tobytes())
        self.colored=f.correlation*self.colored+np.sqrt(1-f.correlation**2)*innovation
        drop=False
        if active:
            delayed=self.buffer[0]
            biased=delayed*(1+np.array([f.voltage_bias_fraction]*2+[f.current_bias_fraction]*2))
            measured=biased+f.relative_std*np.abs(delayed)*self.colored
            drop=self.active_index < f.outage_steps or drop_draw < f.dropout_probability
            self.active_index+=1
            if drop and self.last_valid is not None:
                measured=self.last_valid
                self.stale_steps+=1
                self.dropout_count+=1
            else:
                self.stale_steps=0
                self.last_valid=measured.copy()
        else:
            measured=values
            self.last_valid=values.copy()
            self.stale_steps=0
        # 与既有观测装饰器相同的量测下界；不改变真实对象或真实 PWM。
        measured=np.maximum(measured,np.array([1.0,1.0,0.0,0.0]))
        self.update_count+=1
        valid=observation.electrical_measurement_valid and not (drop and self.missing_policy=="safe_exit")
        return replace(observation,**dict(zip(CHANNELS,measured)),electrical_measurement_valid=valid)

    def compute(self, observation):
        measured=self.perturb(observation)
        command=self.inner.compute(measured)
        record=self.inner.last_identification
        mode=self.inner.identifier.filter_mode
        covariance=self.inner.identifier._active_filter(mode).covariance if record is None else None
        d=self.diagnostics
        values=dict(time_s=observation.time_s,stale_steps=self.stale_steps,
            weight_norm=float(np.linalg.norm(self.inner.rhonn.tunable_weight_matrix)),
            covariance_trace=record.covariance_trace if record is not None else float(np.trace(covariance)),
            covariance_min_eigenvalue=record.covariance_min_eigenvalue if record is not None else float(np.min(np.linalg.eigvalsh(covariance))),
            normalised_innovation=record.normalised_innovation if record is not None and record.normalised_innovation is not None else np.nan,
            filter_mode=int(record.filter_mode=="ukf") if record is not None else -1,
            switched=int(record.decision.switched) if record is not None else 0,
            measurement_valid=int(measured.electrical_measurement_valid),
            innovation_expected=int(record is not None and record.prediction_used is not None))
        for key in d:
            d[key].append(values[key])
        return command

    def audit(self):
        d=self.diagnostics
        finite=all(np.all(np.isfinite(d[key])) for key in ("weight_norm","covariance_trace","covariance_min_eigenvalue"))
        expected=np.asarray(d["innovation_expected"],dtype=bool)
        return dict(updates=self.update_count,dropout_steps=self.dropout_count,
            missing_policy=self.missing_policy,rejected_measurements=int(np.sum(np.asarray(d["measurement_valid"])==0)),
            innovation_checks=int(np.sum(expected)),
            max_stale_steps=max(d["stale_steps"],default=0),finite_weights_covariance=bool(finite),
            finite_post_startup_innovations=bool(np.all(np.isfinite(np.asarray(d["normalised_innovation"])[expected]))),
            max_weight_norm=max(d["weight_norm"],default=None),
            max_covariance_trace=max(d["covariance_trace"],default=None),
            min_covariance_eigenvalue=min(d["covariance_min_eigenvalue"],default=None),
            standard_innovations_sha256=self.innovation_digest.hexdigest(),
            hold_policy="保留最近有效电气量测；安全退出依赖明确缺测标志，时间戳、功率与充电许可使用本拍值，不绕过量测读取真值")
