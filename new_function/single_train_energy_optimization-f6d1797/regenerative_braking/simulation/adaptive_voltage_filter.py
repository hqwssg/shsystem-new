"""显式研究：过去电压变化残差调节电容校正强度，健康时恢复原系数。"""
import math

import numpy as np

from .controllers import ControllerError
from .sink_current_filter import SinkFilteredCurrentFilter


class AdaptiveVoltageCurrentFilter(SinkFilteredCurrentFilter):
    def __init__(self, *, voltage_alpha_noisy=.0125, variation_low_v=1., variation_high_v=4.,
                 variation_time_s=.01, output_current_alpha_noisy=None, **kwargs):
        quiet = kwargs.get("voltage_alpha", .05)
        values = (voltage_alpha_noisy, variation_low_v, variation_high_v, variation_time_s)
        if any(isinstance(v, (bool, np.bool_)) or not math.isfinite(v) for v in values):
            raise ControllerError("自适应电压参数必须有限且非bool")
        if (not 0 < voltage_alpha_noisy <= quiet or not 0 <= variation_low_v < variation_high_v or
                variation_time_s < kwargs["sample_time_s"]):
            raise ControllerError("自适应电压系数、残差门槛或时间常数非法")
        self.voltage_alpha_quiet, self.voltage_alpha_noisy = float(quiet), float(voltage_alpha_noisy)
        self.variation_low_v, self.variation_high_v = float(variation_low_v), float(variation_high_v)
        self.variation_time_s = float(variation_time_s)
        self.output_current_alpha_quiet = float(kwargs.get("output_current_alpha", 1.))
        if output_current_alpha_noisy is not None and (
                isinstance(output_current_alpha_noisy, (bool, np.bool_)) or
                not math.isfinite(output_current_alpha_noisy) or
                not 0 < output_current_alpha_noisy <= self.output_current_alpha_quiet):
            raise ControllerError("自适应储能电流滤波系数非法")
        self.output_current_alpha_noisy = output_current_alpha_noisy
        super().__init__(**kwargs)

    def clear(self):
        super().clear()
        self._variation_sample = None
        self._variation_square = 0.
        self.voltage_alpha = self.voltage_alpha_quiet
        self.output_current_filter.alpha = self.output_current_alpha_quiet

    def reset(self):
        super().reset()
        self.voltage_schedule = []

    def apply(self, observation):
        # alpha仅由过去样本的EWMA决定。本拍残差在apply返回前保存，下一拍才消费。
        rms = math.sqrt(self._variation_square)
        activity = float(np.clip((rms-self.variation_low_v)/(self.variation_high_v-self.variation_low_v), 0., 1.))
        self.voltage_alpha = (self.voltage_alpha_quiet if activity == 0. else self.voltage_alpha_noisy if activity == 1. else
            self.voltage_alpha_quiet+activity*(self.voltage_alpha_noisy-self.voltage_alpha_quiet))
        if self.output_current_alpha_noisy is not None:
            quiet, noisy = self.output_current_alpha_quiet, self.output_current_alpha_noisy
            self.output_current_filter.alpha = quiet if activity == 0. else noisy if activity == 1. else quiet+activity*(noisy-quiet)
            if self.output_current_filter.alpha == 1.:
                self.output_current_filter.clear()
        previous, d2 = self._variation_sample, self._d2
        processed = super().apply(observation)
        if self._variation_sample is not previous:
            rms = 0.  # 缺测/拒充/时间缺口已清记忆；记录实际用于该拍的重锚状态。
        residual = None
        if self._state is not None:
            if previous is not None and self._variation_sample is previous and d2 is not None:
                v, current, sink = previous
                expected_delta = self.sample_time_s/self.output_capacitance_f*((1-d2)*current-sink)
                residual = float(observation.output_voltage_v-v-expected_delta)
                self._variation_square += self.sample_time_s/self.variation_time_s*(residual*residual-self._variation_square)
            self._variation_sample = (observation.output_voltage_v, observation.inductor_current_a, observation.output_current_a)
        self.voltage_schedule.append((observation.time_s, self.voltage_alpha, rms,
            np.nan if residual is None else residual, int(processed.electrical_measurement_valid), self.output_current_filter.alpha))
        return processed

    def audit(self):
        return dict(**super().audit(), voltage_adaptation=dict(data_status="assumed", review_required=True,
            alpha_quiet=self.voltage_alpha_quiet, alpha_noisy=self.voltage_alpha_noisy,
            variation_low_v=self.variation_low_v, variation_high_v=self.variation_high_v,
            variation_time_s=self.variation_time_s, rms_v=math.sqrt(self._variation_square),
            output_current_alpha_quiet=self.output_current_alpha_quiet,
            output_current_alpha_noisy=self.output_current_alpha_noisy,
            timing="过去原始电压增量减去标称电容和已执行占空比对应的预测增量；本拍残差供下一拍使用",
            dependency="标称电容为占位参数；不读取对象电阻电感真值、噪声窗口、随机种子、相关系数或状态真值"))
