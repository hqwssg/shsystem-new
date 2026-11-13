"""显式研究：上一拍模型置信度驱动 PWM 平滑，拒充仍立即归零。"""
import math

from ..control.nsmc import NSMC, NSMCError


class ConfidenceSmoothedNSMC(NSMC):
    def __init__(self, *, confidence_source, alpha_low, alpha_high, smoothing_time_s, **kwargs):
        ts = kwargs["sample_time_s"]
        if (any(isinstance(v, bool) or not math.isfinite(v)
                for v in (alpha_low, alpha_high, smoothing_time_s)) or
                not 0 < alpha_low <= alpha_high <= 1 or smoothing_time_s < ts):
            raise NSMCError("条件平滑需要0<low<=high<=1，时间常数不小于Ts")
        confidence = getattr(confidence_source, "_model_confidence", None)
        if confidence is None or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise NSMCError("条件平滑需要提供[0,1]内有限模型置信度的来源")
        self.confidence_source = confidence_source
        self.alpha_low, self.alpha_high = alpha_low, alpha_high
        self.smoothing_time_s = smoothing_time_s
        super().__init__(**kwargs)
        self._smoothing_alpha = self.alpha_high
        self.minimum_alpha = self.maximum_alpha = self._smoothing_alpha
        self.alpha_updates = 0

    def reset(self):
        super().reset()
        self._smoothing_alpha = self.alpha_high
        self.minimum_alpha = self.maximum_alpha = self._smoothing_alpha
        self.alpha_updates = 0

    def accept_applied_command(self, command):
        super().accept_applied_command(command)
        if command.duty_cycle_T1 == command.duty_cycle_T2 == 0:
            self._smoothing_alpha = self.alpha_high

    def compute(self, observation):
        if observation.storage_charge_power_limit_w == 0:
            self._smoothing_alpha = self.alpha_high
        return super().compute(observation)

    def _resolve_smoothing_alpha(self, observation):
        # ClosedLoopController在NSMC计算之后才写入当拍创新，故此处仅有过去创新。
        confidence = self.confidence_source._model_confidence
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise NSMCError("模型置信度必须为[0,1]内有限数")
        target = self.alpha_low + (self.alpha_high - self.alpha_low) * confidence
        self._smoothing_alpha += self.sample_time_s / self.smoothing_time_s * (target - self._smoothing_alpha)
        self.minimum_alpha = min(self.minimum_alpha, self._smoothing_alpha)
        self.maximum_alpha = max(self.maximum_alpha, self._smoothing_alpha)
        self.alpha_updates += 1
        return self._smoothing_alpha

    def smoothing_audit(self):
        return dict(data_status="assumed", review_required=True, alpha_low=self.alpha_low,
            alpha_high=self.alpha_high, time_s=self.smoothing_time_s,
            minimum_alpha=self.minimum_alpha, maximum_alpha=self.maximum_alpha,
            updates=self.alpha_updates, timing="仅使用上拍辨识新息")
