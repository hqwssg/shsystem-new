"""显式研究：过去量测残差的两档强度调度及可观测静稳恢复。"""
import math

import numpy as np

from .controllers import ControllerError
from .sink_current_filter import SinkFilteredCurrentFilter


class NoiseRecoveryFilter(SinkFilteredCurrentFilter):
    """增量残差开启弱噪声档，量测减滤波量的RMS开启强噪声档。

    两个EWMA均在本拍处理后更新，仅供下一拍系数使用。连续静稳增量可释放
    噪声记忆并重锚电压；它是观测条件，不读取生成器退出时间或真实R/L。
    全部阈值为assumed，默认工厂不装配该研究类。
    """

    def __init__(self, *, voltage_alpha_weak=.025, voltage_alpha_strong=.00625,
                 output_current_alpha_strong=.05, increment_low_v=1., increment_high_v=4.,
                 level_low_v=20., level_high_v=35., intensity_time_s=.01,
                 quiet_increment_v=.5, recovery_ticks=0, warmup_ticks=0, **kwargs):
        quiet = kwargs.get("voltage_alpha", .05)
        values = (voltage_alpha_weak, voltage_alpha_strong, output_current_alpha_strong,
                  increment_low_v, increment_high_v, level_low_v, level_high_v,
                  intensity_time_s, quiet_increment_v)
        if any(isinstance(v, (bool, np.bool_)) or not math.isfinite(v) for v in values):
            raise ControllerError("噪声强度调度参数须为有限非bool数")
        if (not 0 < voltage_alpha_strong <= voltage_alpha_weak <= quiet or
                not 0 < output_current_alpha_strong <= kwargs.get("output_current_alpha", 1.) or
                not 0 <= increment_low_v < increment_high_v or not 0 <= level_low_v < level_high_v or
                intensity_time_s < kwargs["sample_time_s"] or quiet_increment_v < 0):
            raise ControllerError("噪声强度系数、门槛或时间常数非法")
        for ticks in (recovery_ticks, warmup_ticks):
            if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 0:
                raise ControllerError("恢复/启动计数须为非负非bool整数")
        self.voltage_alpha_quiet = float(quiet)
        self.voltage_alpha_weak, self.voltage_alpha_strong = float(voltage_alpha_weak), float(voltage_alpha_strong)
        self.output_current_alpha_quiet = float(kwargs.get("output_current_alpha", 1.))
        self.output_current_alpha_strong = float(output_current_alpha_strong)
        self.increment_low_v, self.increment_high_v = float(increment_low_v), float(increment_high_v)
        self.level_low_v, self.level_high_v = float(level_low_v), float(level_high_v)
        self.intensity_time_s, self.quiet_increment_v = float(intensity_time_s), float(quiet_increment_v)
        self.recovery_ticks = recovery_ticks
        self.warmup_ticks = warmup_ticks
        super().__init__(**kwargs)

    def clear(self):
        super().clear()
        self._increment_sample = None
        self._increment_square = self._level_square = 0.
        self._quiet_count = 0
        self._noise_active = False
        self._strong_activity = 0.
        self._active_ticks = 0
        self.voltage_alpha = self.voltage_alpha_quiet
        self.output_current_filter.alpha = self.output_current_alpha_quiet

    def reset(self):
        super().reset()
        self.recovery_schedule = []
        self.recovery_events = 0

    def accept_applied_command(self, command):
        super().accept_applied_command(command)
        self._active_ticks = (self._active_ticks+1 if command.duty_cycle_T1 != 0 or
                              command.duty_cycle_T2 != 0 else 0)

    def apply(self, observation):
        inc_rms, level_rms = math.sqrt(self._increment_square), math.sqrt(self._level_square)
        weak = float(np.clip((inc_rms-self.increment_low_v)/(self.increment_high_v-self.increment_low_v), 0., 1.))
        strong = float(np.clip((level_rms-self.level_low_v)/(self.level_high_v-self.level_low_v), 0., 1.))
        weak = max(weak, strong)
        warming = self._active_ticks < self.warmup_ticks
        if warming:
            # 仅按过去实际PWM等待启动瞬态；不读取绝对时间或噪声起点。
            self._increment_square = self._level_square = 0.
            weak = strong = inc_rms = level_rms = 0.
        contiguous = (self._time_s is not None and
                      0 < observation.time_s-self._time_s <= self.sample_time_s*(1+1e-7))
        release = bool(self.recovery_ticks and self._quiet_count >= self.recovery_ticks and self._noise_active
                       and not warming and contiguous and observation.electrical_measurement_valid
                       and observation.storage_charge_power_limit_w != 0)
        if release:
            # 仅将电压预测状态重锚；保留已执行PWM、RHONN以及投影参考状态。
            self._release_voltage_state()
            self._increment_square = self._level_square = 0.
            self._noise_active = False
            weak = strong = inc_rms = level_rms = 0.
            self.recovery_events += 1
        self._strong_activity = strong
        self.voltage_alpha, self.output_current_filter.alpha = self._filter_alphas(weak, strong)
        if self.output_current_filter.alpha == 1.:
            self.output_current_filter.clear()
        previous, d2 = self._increment_sample, self._d2
        processed = super().apply(observation)
        if self._increment_sample is not previous:
            weak = strong = inc_rms = level_rms = 0.
            warming = self._active_ticks < self.warmup_ticks
        increment = level = np.nan
        if self._state is not None:
            level = float(observation.output_voltage_v-processed.output_voltage_v)
            eta = self.sample_time_s/self.intensity_time_s
            self._level_square += eta*(level*level-self._level_square)
            if previous is not None and self._increment_sample is previous and d2 is not None:
                voltage, current, sink = previous
                expected = self.sample_time_s/self.output_capacitance_f*((1-d2)*current-sink)
                increment = float(observation.output_voltage_v-voltage-expected)
                self._increment_square += eta*(increment*increment-self._increment_square)
                self._quiet_count = self._quiet_count+1 if abs(increment) <= self.quiet_increment_v else 0
            self._increment_sample = (observation.output_voltage_v, observation.inductor_current_a, observation.output_current_a)
            self._noise_active |= weak > 0. or strong > 0.
        self.recovery_schedule.append((observation.time_s, inc_rms, level_rms, weak, strong,
                                       self.voltage_alpha, self.output_current_filter.alpha,
                                       increment, level, int(release), int(warming), self._active_ticks))
        return processed

    def _filter_alphas(self, weak, strong):
        """保留原算术顺序；研究子类可在消费本拍量测前调度系数。"""
        return (self.voltage_alpha_quiet + weak*(self.voltage_alpha_weak-self.voltage_alpha_quiet)
                + strong*(self.voltage_alpha_strong-self.voltage_alpha_weak),
                self.output_current_alpha_quiet +
                strong*(self.output_current_alpha_strong-self.output_current_alpha_quiet))

    def _release_voltage_state(self):
        """默认保持原立即重锚；显式研究子类可消融电压跳变。"""
        self._state = None

    def audit(self):
        return dict(**super().audit(), noise_recovery=dict(data_status="assumed", review_required=True,
            voltage_alpha_quiet=self.voltage_alpha_quiet, voltage_alpha_weak=self.voltage_alpha_weak,
            voltage_alpha_strong=self.voltage_alpha_strong, output_current_alpha_strong=self.output_current_alpha_strong,
            increment_low_v=self.increment_low_v, increment_high_v=self.increment_high_v,
            level_low_v=self.level_low_v, level_high_v=self.level_high_v, intensity_time_s=self.intensity_time_s,
            quiet_increment_v=self.quiet_increment_v, recovery_ticks=self.recovery_ticks,
            warmup_ticks=self.warmup_ticks,
            recovery_events=self.recovery_events,
            timing="使用过去增量和量测减滤波值的残差，以及连续历史静稳增量",
            dependency="标称电容为占位参数；不读取对象电阻电感真值或噪声生成器元数据"))
