"""显式研究候选的因果电气量测预滤波；不读取对象真值。"""
from dataclasses import replace

import numpy as np

from .controllers import ControllerError

ELECTRICAL_CHANNELS = ("input_voltage_v", "output_voltage_v", "inductor_current_a", "output_current_a")

#: 主算法默认**只滤电压**。
#:
#: 电感电流是内环的快速反馈：0.5 mH 上 1500 V 的电压差就是 3e6 A/s 的电流变化率，
#: 1.9 ms 的滞后等于把电流低估约 5.7 kA。实测（`dt = 4e-4`、s1、逐样本记录）：
#: 四通道滤波把 i_L 峰值从 2595 A 抬到 **4032 A**（额定 3000 A），而只滤电压时
#: 峰值 2563 A、回收能量几乎不变（0.4227 vs 0.4231 kWh）。
#: 因此电压可以滤（母线动态是毫秒~十毫秒级），电流不能滤。
DEFAULT_FILTER_CHANNELS = ("input_voltage_v", "output_voltage_v")


class ElectricalMeasurementFilter:
    """选定电气通道的同系数一阶 IIR，y_k=alpha*x_k+(1-alpha)*y_{k-1}。

    alpha=1 为默认逐位旁路。显式启用时仅滤电气量，功率请求、时间、
    SOC、BMS许可与缺测标志保持当前拍。缺测/拒充/时间缺口清除记忆，
    下一有效拍以新量测初始化，避免继续使用过期状态。

    默认通道集合是 :data:`DEFAULT_FILTER_CHANNELS`（**只含两个电压**），
    ``__init__`` 与 :meth:`from_time_constant` 取同一默认值——否则同一开关
    换个构造入口就会连带换掉带宽。要复现四通道历史消融，需显式传
    ``channels=ELECTRICAL_CHANNELS``。
    """

    def __init__(self, *, alpha=1.0, sample_time_s, channels=DEFAULT_FILTER_CHANNELS):
        if isinstance(alpha, (bool, np.bool_)) or not np.isfinite(alpha) or not 0 < alpha <= 1:
            raise ControllerError("量测滤波alpha必须为(0,1]内有限数，不能为布尔值")
        if isinstance(sample_time_s, (bool, np.bool_)) or not np.isfinite(sample_time_s) or sample_time_s <= 0:
            raise ControllerError("量测滤波周期必须为正有限数，不能为布尔值")
        self.alpha = float(alpha)
        self.sample_time_s = float(sample_time_s)
        if not isinstance(channels, (tuple,list)) or not channels or any(not isinstance(key,str) or key not in ELECTRICAL_CHANNELS for key in channels) or len(set(channels)) != len(channels):
            raise ControllerError("量测滤波通道必须为非空、不重复的电气字段白名单")
        self.channels = tuple(channels)
        self.reset()

    @classmethod
    def from_time_constant(
        cls, *, time_constant_s: float, sample_time_s: float, channels=DEFAULT_FILTER_CHANNELS
    ) -> "ElectricalMeasurementFilter":
        """按**物理时间常数**构造，而不是按每拍系数。

        一阶 IIR 的时间常数是 ``tau = -Ts / ln(1 - alpha)``，反解得
        ``alpha = 1 - exp(-Ts / tau)``。用 ``tau`` 而不是 ``alpha`` 指定强度，
        是为了让同一套参数在任意步长下保持**相同的物理带宽**——本项目跨 ``Ts``
        的数字不能直接比较，若把每拍系数当常数抄过去，滤波强度会被步长悄悄改变。
        """

        if not np.isfinite(time_constant_s) or time_constant_s <= 0:
            raise ControllerError("量测滤波时间常数必须为正有限值")
        if not np.isfinite(sample_time_s) or sample_time_s <= 0:
            raise ControllerError("量测滤波周期必须为正有限数")
        alpha = 1.0 - float(np.exp(-sample_time_s / time_constant_s))
        return cls(alpha=alpha, sample_time_s=sample_time_s, channels=channels)

    def clear(self):
        self._values = None
        self._time_s = None

    def reset(self):
        self.clear()
        self.updates = 0
        self.reanchors = 0

    def apply(self, observation):
        if self.alpha == 1.0:
            return observation
        if not observation.electrical_measurement_valid or observation.storage_charge_power_limit_w == 0:
            self.clear()
            return observation
        values = np.array([getattr(observation, key) for key in self.channels], dtype=float)
        time_s = float(observation.time_s)
        if not np.all(np.isfinite(values)) or not np.isfinite(time_s):
            raise ControllerError("量测滤波输入必须为有限值，不能掩盖非法量测")
        if any(value <= 0 if key.endswith("voltage_v") else value < 0 for key,value in zip(self.channels,values)):
            raise ControllerError("量测滤波要求正电压、非负电流，不能掩盖非法量测")
        if self._time_s is not None:
            interval = time_s-self._time_s
            if interval <= 0:
                raise ControllerError("启用量测滤波时时间必须严格递增")
            if interval > self.sample_time_s*(1+1e-7):
                self.clear()
        if self._values is None:
            self._values = values
            self.reanchors += 1
        else:
            self._values = self.alpha*values+(1-self.alpha)*self._values
        self._time_s = time_s
        self.updates += 1
        return replace(observation, **dict(zip(self.channels, self._values)))

    def audit(self):
        return dict(alpha=self.alpha, sample_time_s=self.sample_time_s,
            enabled=self.alpha < 1, data_status="assumed" if self.alpha < 1 else "disabled",
            channels=self.channels, updates=self.updates, reanchors=self.reanchors,
            timing="参考生成、神经滑模控制与辨识共享因果预滤波；本拍充电许可、功率和荷电状态保持原值")
