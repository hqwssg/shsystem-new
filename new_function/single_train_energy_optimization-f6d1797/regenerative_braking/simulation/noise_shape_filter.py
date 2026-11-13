"""显式研究：过去增量/水平残差RMS比例调度滤波与控制平滑。"""
import math

import numpy as np

from .controllers import ControllerError
from .noise_recovery_filter import NoiseRecoveryFilter


class NoiseShapeFilter(NoiseRecoveryFilter):
    """比例是模型残差的形态代理，不是噪声相关系数或类型的准确辨识。"""

    def __init__(self, *, shape_ratio_low=.5, shape_ratio_high=1., shape_level_floor_v=1.,
                 rapid_voltage_alpha=.0125, rapid_output_current_alpha=.2,
                 recovery_voltage_alpha=None, recovery_ramp_ticks=20, **kwargs):
        values = (shape_ratio_low, shape_ratio_high, shape_level_floor_v,
                  rapid_voltage_alpha, rapid_output_current_alpha)
        if any(isinstance(v, (bool, np.bool_)) or not math.isfinite(v) for v in values):
            raise ControllerError('形态调度参数必须为有限非bool数')
        if (not 0 <= shape_ratio_low < shape_ratio_high or shape_level_floor_v <= 0 or
                not 0 < rapid_voltage_alpha <= kwargs.get('voltage_alpha', .05) or
                not 0 < rapid_output_current_alpha <= kwargs.get('output_current_alpha', 1.)):
            raise ControllerError('形态比例门槛、下限或滤波系数非法')
        self.shape_ratio_low, self.shape_ratio_high = float(shape_ratio_low), float(shape_ratio_high)
        self.shape_level_floor_v = float(shape_level_floor_v)
        self.rapid_voltage_alpha, self.rapid_output_current_alpha = float(rapid_voltage_alpha), float(rapid_output_current_alpha)
        if recovery_voltage_alpha is not None and (isinstance(recovery_voltage_alpha, (bool, np.bool_)) or
                not math.isfinite(recovery_voltage_alpha) or
                not kwargs.get('voltage_alpha', .05) <= recovery_voltage_alpha <= 1.):
            raise ControllerError('渐变重锚系数须介于静稳系数与1之间')
        if isinstance(recovery_ramp_ticks, bool) or not isinstance(recovery_ramp_ticks, int) or recovery_ramp_ticks < 1:
            raise ControllerError('渐变重锚拍数须为正非bool整数')
        self.recovery_voltage_alpha = recovery_voltage_alpha
        self.recovery_ramp_ticks = recovery_ramp_ticks
        super().__init__(**kwargs)

    def clear(self):
        super().clear()
        self.shape_ratio = self.fast_activity = self.fast_smoothing_weight = 0.
        self._recovery_ramp_remaining = 0

    def _release_voltage_state(self):
        if self.recovery_voltage_alpha is None:
            super()._release_voltage_state()
        else:
            # 触发条件仍只读过去静稳样本；保留电压状态，有限拍内增强量测校正。
            self._recovery_ramp_remaining = self.recovery_ramp_ticks

    def reset(self):
        super().reset()
        self.shape_schedule = []

    def _filter_alphas(self, weak, strong):
        # 此钩子在当前残差更新前调用；启动/静稳释放已优先清过去RMS。
        self.shape_ratio = math.sqrt(self._increment_square)/max(
            math.sqrt(self._level_square), self.shape_level_floor_v)
        self.fast_activity = float(np.clip((self.shape_ratio-self.shape_ratio_low)/(
            self.shape_ratio_high-self.shape_ratio_low), 0., 1.)) if weak > 0 or strong > 0 else 0.
        self.fast_smoothing_weight = self.fast_activity*weak
        slow_v, slow_i = super()._filter_alphas(weak, strong)
        fast_v = self.voltage_alpha_quiet+weak*(self.rapid_voltage_alpha-self.voltage_alpha_quiet)
        fast_i = self.output_current_alpha_quiet+weak*(self.rapid_output_current_alpha-self.output_current_alpha_quiet)
        voltage = slow_v+self.fast_activity*(fast_v-slow_v)
        if weak > 0 or strong > 0 or self._active_ticks < self.warmup_ticks:
            self._recovery_ramp_remaining = 0
        if self._recovery_ramp_remaining:
            voltage = self.voltage_alpha_quiet+self._recovery_ramp_remaining/self.recovery_ramp_ticks*(
                self.recovery_voltage_alpha-self.voltage_alpha_quiet)
            self._recovery_ramp_remaining -= 1
        return voltage, slow_i+self.fast_activity*(fast_i-slow_i)

    def apply(self, observation):
        processed = super().apply(observation)
        self.shape_schedule.append((observation.time_s, self.shape_ratio, self.fast_activity,
                                    self.fast_smoothing_weight, self.voltage_alpha, self.output_current_filter.alpha))
        return processed

    def audit(self):
        return dict(**super().audit(), noise_shape=dict(data_status='assumed', review_required=True,
            ratio_low=self.shape_ratio_low, ratio_high=self.shape_ratio_high, level_floor_v=self.shape_level_floor_v,
            rapid_voltage_alpha=self.rapid_voltage_alpha, rapid_output_current_alpha=self.rapid_output_current_alpha,
            recovery_voltage_alpha=self.recovery_voltage_alpha, recovery_ramp_ticks=self.recovery_ramp_ticks,
            timing='上拍补偿电压增量的均方根与上拍量测减滤波值的均方根之比',
            limitation='模型误差也会影响该比值；不读取电阻电感真值、噪声相关系数、随机种子、生成窗口或类型'))
