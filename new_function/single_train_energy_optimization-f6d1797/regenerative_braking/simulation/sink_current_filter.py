"""显式研究：储能端电流因果预滤波，与电容预测及参考共享。"""
from .constraint_aware_current_filter import ConstraintAwareCurrentFilter
from .electrical_measurement_filter import ElectricalMeasurementFilter


class SinkFilteredCurrentFilter(ConstraintAwareCurrentFilter):
    def __init__(self, *, output_current_alpha=1., **kwargs):
        self.output_current_filter = ElectricalMeasurementFilter(alpha=output_current_alpha,
            sample_time_s=kwargs["sample_time_s"], channels=("output_current_a",))
        super().__init__(**kwargs)

    def clear(self):
        super().clear()
        self.output_current_filter.clear()

    def reset(self):
        super().reset()
        self.output_current_filter.reset()

    def apply(self, observation):
        # 不读取对象R、真实电流或噪声时窗；当前BMS/SOC/缺测标志原样传递。
        # 若发生采样间断，需在预滤波更新前先通过多态 clear() 同步重置，
        # 避免 super().apply() 中的间断检测把刚由当前样本重锚定的预滤波状态冲掉。
        if (
            self._time_s is not None
            and observation.electrical_measurement_valid
            and observation.storage_charge_power_limit_w != 0
        ):
            t = float(observation.time_s)
            if t == t and abs(t) != float("inf") and t - self._time_s > self.sample_time_s * (1 + 1e-7):
                self.clear()
        return super().apply(self.output_current_filter.apply(observation))

    def audit(self):
        payload = dict(super().audit())
        if self.output_current_filter.alpha < 1:
            payload["current_channels"] = "电感电流采用预测与校正，输出电流采用因果无限冲激响应滤波"
        return payload | dict(output_current_prefilter=self.output_current_filter.audit(),
            sink_current_timing="本拍因果滤波结果由参考生成与下一拍电容预测共享")
