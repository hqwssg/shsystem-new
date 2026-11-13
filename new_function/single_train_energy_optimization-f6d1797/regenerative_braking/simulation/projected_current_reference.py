"""有界电流反馈的显式动态参考候选；保留RHONN/EKF/UKF/NSMC主链。"""
import numpy as np

from ..tracking import REFERENCE_GUARDED_CURRENT_FEEDBACK, TrackingError


class ProjectedCurrentFeedbackReference:
    """积分储能电流误差，并将积分状态投影到原I-V参考范围。

    z=clip(clip(z_previous,lower,upper)+Ts/tau*R_nom*(P*/Vmeas-Imeas),lower,upper)。
    保存限幅后的z，避免隐藏积分饱和；不把量测电压的噪声直接加到参考。
    tau为assumed研究参数。限幅只约束参考，不代表真实状态的不变集。
    显式prediction_gain_coupling时修正增益乘(1+kappa*beta)，beta来自已处理量测的
    因果预测权重；kappa=0保持旧路径。该耦合仍为assumed消融，不能视作已证实收益。
    """

    data_status = "derived"

    def __init__(self, base, *, sample_time_s, correction_time_s=.001, error_smoothing_alpha=1.,
                 prediction_gain_coupling=0., error_mode="current"):
        if getattr(base, "strategy", None) != REFERENCE_GUARDED_CURRENT_FEEDBACK:
            raise TrackingError("投影积分参考必须装配在有上下界的电流反馈上")
        for name, value in (("sample_time_s", sample_time_s), ("correction_time_s", correction_time_s)):
            if isinstance(value, (bool, np.bool_)) or not np.isfinite(value) or value <= 0:
                raise TrackingError(f"{name}必须为正有限数，不能为布尔值")
        if sample_time_s > correction_time_s:
            raise TrackingError("参考更新周期不能大于修正时间常数")
        if isinstance(error_smoothing_alpha, (bool, np.bool_)) or not np.isfinite(error_smoothing_alpha) or not 0 < error_smoothing_alpha <= 1:
            raise TrackingError("参考误差滤波系数必须为(0,1]内有限数")
        if isinstance(prediction_gain_coupling, (bool, np.bool_)) or not np.isfinite(prediction_gain_coupling) or not -1 < prediction_gain_coupling <= 1:
            raise TrackingError("预测权重增益耦合须为(-1,1]内有限非bool数")
        if error_mode not in ("current", "power"):
            raise TrackingError("参考误差模式必须为 current 或 power")
        self.base = base
        self.sample_time_s = float(sample_time_s)
        self.correction_time_s = float(correction_time_s)
        self.gain = self.sample_time_s / self.correction_time_s
        self.error_smoothing_alpha = float(error_smoothing_alpha)
        self.prediction_gain_coupling = float(prediction_gain_coupling)
        self.error_mode = str(error_mode)
        self.reset()

    def __getattr__(self, key):
        return getattr(self.base, key)

    def clear(self):
        self._voltage = None
        self._time_s = None
        self._error = None
        self._prediction_weight = 0.
        self.last_update = None

    def set_prediction_weight(self, weight):
        """本拍量测预处理之后、参考更新之前传递因果权重；禁止越界或静默截断。"""
        if isinstance(weight, (bool, np.bool_)) or not np.isfinite(weight) or not 0 <= weight <= 1:
            raise TrackingError("预测权重须为[0,1]内有限非bool数")
        self._prediction_weight = float(weight)

    def reset(self):
        self.clear()
        self.updates = 0
        self.reanchors = 0
        self.upper_clip_steps = 0
        self.lower_clip_steps = 0

    def __call__(self, observation):
        if not observation.electrical_measurement_valid:
            self.clear()
            raise TrackingError("缺测时不能构造动态参考")
        # 基础参考复用功率口径与电气输入校验，不重复四项功率限制公式。
        self.base(observation)
        power = self.base.absorbable_power(observation)
        lower, upper = self.base.feedback_voltage_bounds(power)
        time_s = float(observation.time_s)
        if not np.isfinite(time_s):
            raise TrackingError("动态参考时间必须有限")
        if self._time_s is not None:
            interval = time_s - self._time_s
            if interval <= 0:
                raise TrackingError("动态参考时间必须严格递增")
            if interval > self.sample_time_s * (1 + 1e-7):
                current_weight = self._prediction_weight
                self.clear()
                # 本拍已因果重锚的滤波权重仍可消费；过去参考/误差记忆已清除。
                self._prediction_weight = current_weight
        if power == 0 or observation.storage_charge_power_limit_w == 0:
            self.clear()
            return np.array([lower, 0.])
        if self._voltage is None:
            self._voltage = lower
            self.reanchors += 1
        anchor = float(np.clip(self._voltage, lower, upper))
        if self.error_mode == "current":
            error = power / observation.output_voltage_v - observation.output_current_a
        else:
            measured_power = float(observation.output_power_w)
            if not np.isfinite(measured_power):
                raise TrackingError("功率误差参考要求有限输出功率")
            # 输出功率是储能侧上一拍实际功率。转成等效电压误差后，
            # 由同一个 R_nom 映射到参考电压，积分时间常数控制收敛速度。
            error = (power - max(measured_power, 0.0)) / max(observation.output_voltage_v, 1e-9)
        if self.error_smoothing_alpha < 1 and self._error is not None:
            error = self.error_smoothing_alpha * error + (1-self.error_smoothing_alpha) * self._error
        self._error = float(error)
        gain = self.gain
        if self.prediction_gain_coupling:
            gain *= 1+self.prediction_gain_coupling*self._prediction_weight
        raw = anchor + gain * self.base.storage_internal_resistance_ohm * error
        self._voltage = float(np.clip(raw, lower, upper))
        self._time_s = time_s
        self.upper_clip_steps += int(raw > upper)
        self.lower_clip_steps += int(raw < lower)
        self.updates += 1
        self.last_update = (time_s, self._prediction_weight, gain, error, anchor, raw,
                            self._voltage, lower, upper)
        return np.array([self._voltage, min(power / self._voltage, self.base.inductor_current_limit_a)])

    def audit(self):
        return dict(kind="projected_storage_current_integral", data_status="derived", review_required=True,
            parameter_status="assumed", sample_time_s=self.sample_time_s,
            correction_time_s=self.correction_time_s, gain=self.gain,
            error_smoothing_alpha=self.error_smoothing_alpha,
            error_mode=self.error_mode,
            prediction_gain_coupling=self.prediction_gain_coupling,
            prediction_weight=self._prediction_weight,
            updates=self.updates, reanchors=self.reanchors, upper_clip_steps=self.upper_clip_steps,
            lower_clip_steps=self.lower_clip_steps,
            voltage_memory_v=self._voltage, anti_windup="保存投影后的状态，不使用隐藏的无界累加器")
