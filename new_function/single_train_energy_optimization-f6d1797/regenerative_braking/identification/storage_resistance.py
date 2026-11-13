"""储能内阻的在线辨识（由可测量直接反解，不读被控对象真值）。

为什么需要它
------------
参考电压按储能侧二参数模型求解：

    v_ref = (V_oc + sqrt(V_oc^2 + 4·P_abs·R)) / 2

即"要让储能吸收 `P_abs`，母线电压该抬到多少"。式中 `R` 是**装配时的**内阻。
而对象的真实吸收电流是

    i_sink = (v_out − V_oc) / R_true

于是 `v_ref − V_oc` 只取决于**假设的** `R`，却被**真实的** `R` 去除。闭环稳态下
回收功率正比于 `i_sink`，因此

    回收量 ∝ R_assumed / R_true

实测（`dt = 1e-4`、8 s 平直制动剖面，`docs/storage_resistance_identification_2026-11-07.md`）：
`R_true = 1.5/2/3 × R_nom` 时净再生 4.03 → 2.71/2.04/1.36 kWh，比值 1.49/1.97/2.96，
与 `R_true/R_nom` 一一对应；而只要控制器知道真值，三条曲线全部回到 4.02~4.03 kWh。
**这不是滑模面 λ 的问题，是参考量用了一个可测却未测的参数。**

本模块做的事很小：`R` 本来就能从同一拍的量测算出来——

    R_hat = (v_out − V_oc) / i_out

不需要额外传感器，也不需要辨识器收敛。加一阶低通抑制噪声、加截面夹紧防止
小电流下比值病态，就得到可用的在线估计。

工程约束（不是可以随手改的调参项）
--------------------------------
1. **电流太小时不更新**：`i_out` 趋于 0 时比值 `(v_out − V_oc)/i_out` 的条件数爆炸，
   一个 1 V 的量测误差就能给出 1 Ω。低于阈值即保持上一次估计，并计入 `skipped`。
2. **估计值必须夹紧**：内阻是正量，且物理上不可能任意倍数地偏离登记值。
   默认夹在 `[0.25, 4] × R_ref`——下限防除零，上限对应"老化/低温到 4 倍"仍在线性区。
3. **不更新时不得倒推**：`ready` 为假之前控制器继续用装配值，行为与未启用时逐位一致。
4. **`V_oc` 仍取登记的名义电压**：本项目储能模型没有 SOC-OCV 曲线
   （`storage_parameters.json` 的 `storage_bus_model_note`），所以 `V_oc` 是常数；
   若将来引入 OCV(SOC)，这里必须同步改成查表，否则估计值会跟着 SOC 漂。
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..simulation.controllers import ControllerError

DEFAULT_MIN_FACTOR = 0.25
DEFAULT_MAX_FACTOR = 4.0


class StorageResistanceEstimator:
    """由 ``(v_out, i_out)`` 反解储能内阻的一阶低通估计器。

    ``time_constant_s`` 以**物理时间**给出，构造时按 ``sample_time_s`` 折算每拍系数
    ``alpha = 1 − exp(−Ts/τ)``——与量测预滤波同一纪律：跨步长的数字不可比，
    不能把每拍系数当常数抄到另一个步长。
    """

    def __init__(
        self,
        *,
        reference_resistance_ohm: float,
        open_circuit_voltage_v: float,
        min_current_a: float,
        time_constant_s: float,
        sample_time_s: float,
        min_factor: float = DEFAULT_MIN_FACTOR,
        max_factor: float = DEFAULT_MAX_FACTOR,
        startup_time_constant_s: Optional[float] = None,
        startup_duration_s: float = 0.0,
    ) -> None:
        for name, value in (
            ("reference_resistance_ohm", reference_resistance_ohm),
            ("open_circuit_voltage_v", open_circuit_voltage_v),
            ("min_current_a", min_current_a),
            ("time_constant_s", time_constant_s),
            ("sample_time_s", sample_time_s),
        ):
            if isinstance(value, (bool, np.bool_)) or not np.isfinite(value) or value <= 0.0:
                raise ControllerError(f"储能内阻估计的 {name} 必须为正有限数，不能为布尔值")
        if (
            isinstance(min_factor, (bool, np.bool_))
            or isinstance(max_factor, (bool, np.bool_))
            or not (np.isfinite(min_factor) and np.isfinite(max_factor))
        ):
            raise ControllerError("储能内阻估计的夹紧系数必须为有限数，不能为布尔值")
        if startup_time_constant_s is not None and (
            isinstance(startup_time_constant_s, (bool, np.bool_))
            or not np.isfinite(startup_time_constant_s)
            or startup_time_constant_s <= 0.0
        ):
            raise ControllerError("启动阶段内阻估计时间常数必须为正有限数")
        if isinstance(startup_duration_s, (bool, np.bool_)) or not np.isfinite(startup_duration_s) or startup_duration_s < 0.0:
            raise ControllerError("启动阶段内阻估计时长必须为非负有限数")
        if startup_time_constant_s is not None and startup_duration_s <= 0.0:
            raise ControllerError("启用启动阶段时间常数时必须给出正启动时长")
        if not 0.0 < min_factor < 1.0 < max_factor:
            raise ControllerError(
                f"夹紧系数必须满足 0 < min_factor < 1 < max_factor，实际为 "
                f"({min_factor!r}, {max_factor!r})"
            )
        self.reference_resistance_ohm = float(reference_resistance_ohm)
        self.open_circuit_voltage_v = float(open_circuit_voltage_v)
        self.min_current_a = float(min_current_a)
        self.time_constant_s = float(time_constant_s)
        self.sample_time_s = float(sample_time_s)
        self.min_factor = float(min_factor)
        self.max_factor = float(max_factor)
        self.alpha = 1.0 - math.exp(-self.sample_time_s / self.time_constant_s)
        self.startup_time_constant_s = None if startup_time_constant_s is None else float(startup_time_constant_s)
        self.startup_duration_s = float(startup_duration_s)
        self.startup_alpha = None if self.startup_time_constant_s is None else 1.0 - math.exp(-self.sample_time_s / self.startup_time_constant_s)
        self.reset()

    def reset(self) -> None:
        """回到装配值并清计数（控制器 ``reset()`` 必须调用，避免跨场景热启动）。"""

        self.value_ohm = self.reference_resistance_ohm
        self.updates = 0
        self.skipped = 0
        self.clamped = 0
        self.elapsed_s = 0.0

    @property
    def ready(self) -> bool:
        """是否已有至少一次有效更新（未更新前控制器必须继续用装配值）。"""

        return self.updates > 0

    def update(self, output_voltage_v: float, output_current_a: float) -> float:
        """用一拍量测更新估计值，返回当前估计（Ω）。

        不满足可辨识条件时**保持**上一次估计，不做任何外推。
        """

        voltage = float(output_voltage_v)
        current = float(output_current_a)
        if not np.isfinite(voltage) or not np.isfinite(current):
            raise ControllerError("储能内阻估计的输入必须为有限值，不能掩盖非法量测")
        if current < 0.0:
            raise ControllerError("储能内阻估计要求非负输出电流，不能掩盖非法量测")
        if current < self.min_current_a or voltage <= self.open_circuit_voltage_v:
            # 电流太小 → 比值病态；电压未高于开路电压 → 没在充电，分子无意义。
            self.skipped += 1
            return self.value_ohm

        self.elapsed_s += self.sample_time_s
        raw = (voltage - self.open_circuit_voltage_v) / current
        low = self.min_factor * self.reference_resistance_ohm
        high = self.max_factor * self.reference_resistance_ohm
        if raw < low or raw > high:
            self.clamped += 1
            raw = min(max(raw, low), high)
        alpha = self.alpha
        if self.startup_alpha is not None and self.elapsed_s <= self.startup_duration_s:
            alpha = self.startup_alpha
        self.value_ohm += alpha * (raw - self.value_ohm)
        self.updates += 1
        return self.value_ohm

    def audit(self) -> dict:
        return dict(
            enabled=True,
            reference_ohm=self.reference_resistance_ohm,
            value_ohm=self.value_ohm,
            ratio_of_reference=self.value_ohm / self.reference_resistance_ohm,
            time_constant_s=self.time_constant_s,
            alpha=self.alpha,
            startup_time_constant_s=self.startup_time_constant_s,
            startup_duration_s=self.startup_duration_s,
            startup_alpha=self.startup_alpha,
            elapsed_s=self.elapsed_s,
            min_current_a=self.min_current_a,
            min_factor=self.min_factor,
            max_factor=self.max_factor,
            updates=self.updates,
            skipped=self.skipped,
            clamped=self.clamped,
            data_status="derived",
            formula="R_hat = (v_out - V_oc) / i_out，一阶低通 + 夹紧；不读取被控对象真值",
        )


def build_storage_resistance_estimator(
    *,
    storage_params,
    converter_params,
    time_constant_s: float,
    sample_time_s: float,
    min_current_fraction: float = 0.1,
    startup_time_constant_s: Optional[float] = None,
    startup_duration_s: float = 0.0,
) -> Optional[StorageResistanceEstimator]:
    """按参数对象装配；``time_constant_s <= 0`` 返回 ``None``（显式关闭）。"""

    if time_constant_s is None or time_constant_s <= 0.0:
        return None
    if storage_params is None or converter_params is None:
        raise ControllerError(
            "启用储能内阻在线估计需要同时给出 storage_params 与 converter_params"
        )
    if not 0.0 < min_current_fraction < 1.0:
        raise ControllerError("最小可辨识电流比例必须在 (0,1) 内")
    return StorageResistanceEstimator(
        reference_resistance_ohm=float(storage_params.internal_resistance_ohm),
        open_circuit_voltage_v=float(storage_params.nominal_voltage_v),
        min_current_a=float(converter_params.max_output_current_a) * min_current_fraction,
        time_constant_s=float(time_constant_s),
        sample_time_s=float(sample_time_s),
        startup_time_constant_s=startup_time_constant_s,
        startup_duration_s=float(startup_duration_s),
    )
