"""显式研究候选：过去参考上界活动调节电流预测及电容共享权重。"""
import numpy as np

from .controllers import ControllerError
from .inductor_prediction_filter import InductorPredictionFilter


class ConstraintAwareCurrentFilter(InductorPredictionFilter):
    """用参考上界活动的因果EWMA降低预测权重，不识别或读取真实储能R。

    a <- a + Ts/tau_a * (上拍参考是否触上界 - a)。
    目标权重 = strength * clip((stop-a)/(stop-start),0,1)，再用Ts/tau_w平滑。
    同一权重混合电感预测校正与原始电流，并混合用于下一拍电容预测的电流。
    adaptive=False仅做固定权重消融；权重0复用原电容候选、权重1复用shared02。
    entry_time_s>0时从零权重投入，仅按上拍有效非零功率参考累积线性进度，
    再乘活动目标并平滑；缺测/拒充/时间缺口/零功率/实际零PWM均清投入记忆。
    entry_time_s=0逐位保留旧候选；此机制不检测任意时刻突然出现的噪声。
    所有门槛/时间常数仍assumed，不宣称上界事件是唯一损失原因。
    """

    def __init__(self, *, sharing_strength=1., adaptive=True, activity_start=.6,
                 activity_stop=.8, activity_time_s=.05, weight_time_s=.005,
                 entry_time_s=0., confidence_adaptive=False, confidence_low=.002,
                 confidence_high=.02, confidence_floor=.5, confidence_time_s=.01,
                 confidence_metric="magnitude",
                 **kwargs):
        for key, value in (("sharing_strength", sharing_strength), ("activity_start", activity_start),
                           ("activity_stop", activity_stop), ("activity_time_s", activity_time_s),
                           ("weight_time_s", weight_time_s), ("entry_time_s", entry_time_s),
                           ("confidence_low", confidence_low), ("confidence_high", confidence_high),
                           ("confidence_floor", confidence_floor), ("confidence_time_s", confidence_time_s)):
            if isinstance(value, (bool, np.bool_)) or not np.isfinite(value):
                raise ControllerError(f"{key}必须为有限数且不能为bool")
        if not 0 <= sharing_strength <= 1 or not 0 <= activity_start < activity_stop <= 1:
            raise ControllerError("权重须在[0,1]，活动起止门槛须满足0<=start<stop<=1")
        ts = kwargs.get("sample_time_s", 0.)
        if activity_time_s <= 0 or weight_time_s <= 0 or confidence_time_s <= 0 or ts > min(activity_time_s, weight_time_s, confidence_time_s):
            raise ControllerError("活动/权重/置信度时间常数须为正且不小于采样周期")
        if not 0 <= confidence_low < confidence_high or not 0 <= confidence_floor <= 1:
            raise ControllerError("置信度残差门槛须满足0<=low<high，置信度下限须在[0,1]")
        if confidence_metric not in ("magnitude", "slope"):
            raise ControllerError("confidence_metric必须为magnitude或slope")
        if entry_time_s < 0 or 0 < entry_time_s < ts:
            raise ControllerError("投入渐增时长须为0（禁用）或不小于采样周期")
        if not isinstance(adaptive, bool) or not isinstance(confidence_adaptive, bool):
            raise ControllerError("adaptive和confidence_adaptive必须为bool")
        if kwargs.get("shared_capacitor_current", True) is not True:
            raise ControllerError("约束混合候选要求显式共享电容电流")
        self.sharing_strength = float(sharing_strength)
        self.adaptive = adaptive
        self.activity_start, self.activity_stop = float(activity_start), float(activity_stop)
        self.activity_time_s, self.weight_time_s = float(activity_time_s), float(weight_time_s)
        self.entry_time_s = float(entry_time_s)
        self.confidence_adaptive = confidence_adaptive
        self.confidence_low, self.confidence_high = float(confidence_low), float(confidence_high)
        self.confidence_floor = float(confidence_floor)
        self.confidence_time_s = float(confidence_time_s)
        self.confidence_metric = confidence_metric
        kwargs["shared_capacitor_current"] = True
        super().__init__(**kwargs)

    def clear(self):
        super().clear()
        self.clear_constraint_memory()

    def clear_constraint_memory(self):
        self._upper_event = None
        self._activity = 0.
        self._entry_progress = 0. if self.entry_time_s else 1.
        self._weight = 0. if self.entry_time_s else self.sharing_strength
        self._model_confidence = 1.
        self._confidence_input = None
        self._confidence_updates = 0

    def reset(self):
        super().reset()
        self.weight_updates = 0
        self.reduced_weight_steps = 0
        self.minimum_weight = self._weight

    def observe_reference(self, voltage, lower, upper, power):
        values = np.asarray((voltage, lower, upper, power), dtype=float)
        if not np.all(np.isfinite(values)) or lower <= 0 or upper < lower or power < 0:
            raise ControllerError("参考活动输入必须有限且边界合法")
        if voltage < lower-1e-7 or voltage > upper+1e-7:
            raise ControllerError("参考活动输入不能越过原投影边界")
        if power == 0 or upper == lower:
            self.clear_constraint_memory()
        else:
            self._upper_event = float(voltage >= upper-1e-7)

    def set_model_confidence(self, normalised_innovation):
        """消费上一拍辨识残差，供下一拍共享权重与参考增益使用。

        ``normalised_innovation``来自上一拍RHONN/EKF/UKF记录；没有当前/未来量测。
        残差低于``confidence_low``视为高置信，超过``confidence_high``逐步降至
        ``confidence_floor``，并用因果一阶平滑避免权重跳变。
        """
        if normalised_innovation is None:
            self._confidence_input = None
            return
        value = float(normalised_innovation)
        if not np.isfinite(value) or value < 0:
            raise ControllerError("归一化辨识残差必须为有限非负数")
        metric = value if self.confidence_metric == "magnitude" or self._confidence_input is None else abs(value-self._confidence_input)
        raw = float(np.clip((self.confidence_high-metric)/(self.confidence_high-self.confidence_low), 0., 1.))
        self._confidence_input = value
        self._model_confidence += self.sample_time_s/self.confidence_time_s*(raw-self._model_confidence)
        self._model_confidence = float(np.clip(self._model_confidence, 0., 1.))
        self._confidence_updates += 1

    def _prediction_weights(self):
        if self._upper_event is not None:
            target = self.sharing_strength
            if self.adaptive:
                self._activity += self.sample_time_s/self.activity_time_s*(self._upper_event-self._activity)
                target *= float(np.clip(
                    (self.activity_stop-self._activity)/(self.activity_stop-self.activity_start), 0., 1.))
            if self.entry_time_s:
                # 仅累计过去有效且有吸收功率的参考拍；不读取故障时间/噪声参数。
                self._entry_progress = min(1., self._entry_progress+self.sample_time_s/self.entry_time_s)
                target *= self._entry_progress
            if self.confidence_adaptive:
                target *= self.confidence_floor + (1-self.confidence_floor)*self._model_confidence
            if self.adaptive or self.entry_time_s or self.confidence_adaptive:
                self._weight += self.sample_time_s/self.weight_time_s*(target-self._weight)
        self.weight_updates += 1
        self.reduced_weight_steps += int(self._weight < self.sharing_strength-1e-12)
        self.minimum_weight = min(self.minimum_weight, self._weight)
        return self._weight, self._weight

    def audit(self):
        payload = super().audit()
        payload["constraint_sharing"] = dict(data_status="assumed", review_required=True,
            sharing_strength=self.sharing_strength, adaptive=self.adaptive,
            activity_start=self.activity_start, activity_stop=self.activity_stop,
            activity_time_s=self.activity_time_s, weight_time_s=self.weight_time_s,
            entry_time_s=self.entry_time_s, entry_progress=self._entry_progress,
            current_upper_activity=self._activity, current_weight=self._weight,
            minimum_weight=self.minimum_weight, weight_updates=self.weight_updates,
            reduced_weight_steps=self.reduced_weight_steps,
            confidence_adaptive=self.confidence_adaptive, confidence_low=self.confidence_low,
            confidence_high=self.confidence_high, confidence_floor=self.confidence_floor,
            confidence_time_s=self.confidence_time_s, model_confidence=self._model_confidence,
            confidence_metric=self.confidence_metric, confidence_input=self._confidence_input,
            confidence_updates=self._confidence_updates,
            timing="使用上拍参考投影事件与辨识残差；不读取本拍或未来参考及电阻电感真值")
        return payload


class ReferenceConstraintFeedback:
    """参考只计算一次；当前投影结果仅供下一拍滤波权重使用。"""

    def __init__(self, reference, measurement_filter):
        self.inner = reference
        self.measurement_filter = measurement_filter

    def __getattr__(self, key):
        return getattr(self.inner, key)

    def clear(self):
        self.inner.clear()
        self.measurement_filter.clear_constraint_memory()

    def reset(self):
        self.inner.reset()
        self.measurement_filter.clear_constraint_memory()

    def __call__(self, observation):
        if self.inner.prediction_gain_coupling:
            # 本拍滤波权重已由上拍参考产生；当前参考事件只供下一拍使用。
            self.inner.set_prediction_weight(self.measurement_filter._weight)
        result = self.inner(observation)
        power = self.inner.absorbable_power(observation)
        lower, upper = self.inner.feedback_voltage_bounds(power)
        self.measurement_filter.observe_reference(result[0], lower, upper, power)
        return result

    def audit(self):
        return dict(**self.inner.audit(), constraint_feedback="本拍参考事件供下一量测拍使用")
