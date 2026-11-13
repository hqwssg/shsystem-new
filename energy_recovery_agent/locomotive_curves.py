"""机车牵引计算特性曲线加载与插值查询。

数据来源：``data/real_shuohuang/locomotive_curves.json``（TB/T 1407.1-2018 人工取点）。

本模块只做只读查询，不修改任何输入数据；供 ``train_simulator`` 按机车类型与速度
插值取电制动力、再生电流、单位基本阻力等特性值。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import json


def _load_curves(path: Path) -> dict:
    """加载机车特性曲线 JSON，找不到文件时返回空字典。"""

    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


class LocomotiveCurveBank:
    """按机型提供速度相关的特性曲线插值查询。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        """函数 __init__：加载曲线库。``path`` 缺省时用项目默认数据路径。"""

        if path is None:
            path = Path(__file__).resolve().parent / "data" / "real_shuohuang" / "locomotive_curves.json"
        raw = _load_curves(path)
        self._locomotives: Dict[str, dict] = raw.get("locomotives", {})
        self._freight = raw.get("freight_resistance_coeffs", {})
        self._adhesion = raw.get("adhesion_formulas", {})
        self._derating = raw.get("multi_loco_derating", {})
        self._regen_formula = raw.get("regen_energy_formula", {})
        self._loaded = bool(self._locomotives)

    @property
    def available_types(self) -> List[str]:
        """可用机车类型标识列表。"""

        return list(self._locomotives)

    def is_regenerative(self, locomotive_type: str) -> bool:
        """该机型是否具备再生制动（回馈电网）能力。"""

        loco = self._locomotives.get(locomotive_type)
        return bool(loco and loco.get("regenerative"))

    def _curve(self, locomotive_type: str, key: str) -> Optional[List[dict]]:
        """取某机型的某条曲线点列表，缺失返回 None。"""

        loco = self._locomotives.get(locomotive_type)
        if not loco:
            return None
        curve = loco.get(key)
        if not curve and locomotive_type == "SHENHUA_8":
            fallback = self._locomotives.get("HXD1_25t")
            if fallback:
                curve = fallback.get(key)
        if not curve:
            return None
        points = curve.get("points")
        return points if points else None

    @staticmethod
    def _interpolate(points: List[dict], x_key: str, y_key: str, x: float) -> Optional[float]:
        """在按 x 升序的点列表上做线性插值，x 越界时取端点值。"""

        if not points:
            return None
        xs = [float(p[x_key]) for p in points]
        ys = [float(p[y_key]) for p in points]
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        for i in range(len(xs) - 1):
            if xs[i] <= x <= xs[i + 1]:
                if xs[i + 1] == xs[i]:
                    return ys[i]
                t = (x - xs[i]) / (xs[i + 1] - xs[i])
                return ys[i] + t * (ys[i + 1] - ys[i])
        return ys[-1]

    def brake_force_kN(self, locomotive_type: str, speed_kmh: float) -> Optional[float]:
        """电制动力 B_d(kN)，按速度插值；无该机型曲线时返回 None。"""

        points = self._curve(locomotive_type, "brake_curve")
        if points is None:
            return None
        return self._interpolate(points, "v", "Bd", speed_kmh)

    def regen_current_A(self, locomotive_type: str, speed_kmh: float) -> Optional[float]:
        """再生制动发电有功电流 I_z(A)，按速度插值；无曲线时返回 None。"""

        points = self._curve(locomotive_type, "regen_current_curve")
        if points is None:
            return None
        return self._interpolate(points, "v", "I", speed_kmh)

    def unit_resistance_N_per_kN(self, locomotive_type: str, speed_kmh: float) -> Optional[float]:
        """机车单位基本阻力 w0'(N/kN)，按速度插值；无曲线时返回 None。"""

        points = self._curve(locomotive_type, "unit_resistance_curve")
        if points is None:
            return None
        return self._interpolate(points, "v", "w", speed_kmh)

    def adhesion_traction_kN(self, locomotive_type: str, speed_kmh: float) -> Optional[float]:
        """黏着限制牵引力 F_mu(kN)，按速度插值；无曲线时返回 None。"""

        points = self._curve(locomotive_type, "adhesion_traction_curve")
        if points is None:
            return None
        return self._interpolate(points, "v", "F", speed_kmh)

    def locomotive_params(self, locomotive_type: str) -> Optional[dict]:
        """取某机型的表10参数（计算重量、持续牵引力等），缺失返回 None。"""

        loco = self._locomotives.get(locomotive_type)
        if not loco:
            return None
        return loco.get("params")

    def locomotive_resistance_coeffs(self, locomotive_type: str) -> Optional[dict]:
        """取某机型的单位基本阻力系数（表2），返回 {A, B, C}；缺失返回 None。"""

        loco = self._locomotives.get(locomotive_type)
        if not loco:
            return None
        coeffs = loco.get("resistance_coeffs")
        if not coeffs:
            return None
        return {"A": coeffs.get("A"), "B": coeffs.get("B"), "C": coeffs.get("C")}

    def locomotive_power_kW(self, locomotive_type: str) -> Optional[float]:
        """由表10 持续牵引力与持续速度推导单台机车持续功率（kW）。

        P = F_持续(kN) × v_持续(m/s)。对 HXD1(23t) 即 493.7 × 70/3.6 ≈ 9600 kW。
        表10 未直接给功率，这是从持续工况反推的等效持续功率。
        """

        params = self.locomotive_params(locomotive_type)
        if not params:
            return None
        force_kn = params.get("continuous_traction_kN")
        speed_kmh = params.get("continuous_speed_kmh")
        if force_kn is None or speed_kmh is None or speed_kmh <= 0:
            return None
        return float(force_kn) * float(speed_kmh) / 3.6

    @property
    def freight_resistance(self) -> dict:
        """货车单位基本阻力系数（表5）。"""

        return self._freight

    def freight_resistance_coeffs(self, load_state: str) -> Optional[dict]:
        """取货车单位基本阻力系数（表5），load_state 为 ``loaded``/``empty``。

        返回 {A, B, C}（N/kN 口径，v 单位 km/h）；未知状态返回 None。
        """

        entry = self._freight.get(load_state)
        if not entry:
            return None
        return {"A": entry.get("A"), "B": entry.get("B"), "C": entry.get("C")}

    @property
    def adhesion_formulas(self) -> dict:
        """黏着系数公式（4.11 制动黏着 + 5.2 牵引黏着）。"""

        return self._adhesion

    def brake_adhesion_coefficient(self, speed_kmh: float, condition: str = "dry") -> Optional[float]:
        """制动黏着系数 μz（式52-54）。condition: dry / wet_without_antiskid / wet_with_antiskid。"""

        brake = self._adhesion.get("brake", {})
        entry = brake.get(condition)
        if not entry:
            return None
        v = max(0.0, speed_kmh)
        if condition == "dry":
            return 0.0624 + 45.60 / (260.0 + v)
        if condition == "wet_without_antiskid":
            return 0.0405 + 13.55 / (120.0 + v)
        if condition == "wet_with_antiskid":
            return 0.0486 + 13.55 / (120.0 + v)
        return None

    def traction_adhesion_coefficient(self, speed_kmh: float, series: str = "SS") -> Optional[float]:
        """牵引黏着系数 μj（式55-57）。series: SS / 8G / 8K。HXD 系列无静态公式，返回 None。"""

        v = max(0.0, speed_kmh)
        if series == "SS":
            return 0.24 + 12.0 / (100.0 + 8.0 * v)
        if series == "8G":
            return 0.28 + 4.0 / (50.0 + 6.0 * v) - 0.0006 * v
        if series == "8K":
            return 0.38 * (10.0 + 0.11 * v) / (10.0 + 0.2 * v)
        return None

    @property
    def multi_loco_derating(self) -> dict:
        """多机牵引制动力折减规则（5.4节）。"""

        return self._derating

    def multi_loco_derating_factor(self, operation_mode: str = "coupled") -> float:
        """多机折减系数。coupled=重联/同步操纵(1.0)、separate=分别操纵(0.98)、pusher=推送补机(0.95)。

        从 JSON 的 multi_loco_derating 规则表读取，找不到时回退 1.0（最保守不过度折减）。
        """

        aliases = {
            "coupled": ("多机重联", "同步操纵", "重联"),
            "separate": ("分别操纵",),
            "pusher": ("推送补机", "补机"),
        }
        keywords = aliases.get(operation_mode, aliases["coupled"])
        for rule in self._derating.get("rules", []):
            condition = str(rule.get("condition", ""))
            if any(k in condition for k in keywords):
                return float(rule.get("factor_per_loco", 1.0))
        return 1.0

    def regen_network_voltage_kV(self) -> Optional[float]:
        """牵引网电压 U_w(kV)，用于式(72) 再生电量积分。

        取值来自 JSON 的 ``U_w_kV``，当前为智能电表网压字段实测中位值 27.2 kV；
        数据来源见 ``regen_voltage_status()``。
        """

        formula = getattr(self, "_regen_formula", None)
        if not formula:
            return None
        value = formula.get("U_w_kV")
        return float(value) if value is not None else None

    def regen_voltage_status(self) -> str:
        """U_w 的数据状态标记，用于报告里区分「实测」与「虚拟占位」。"""

        formula = getattr(self, "_regen_formula", None)
        if not formula:
            return "unavailable"
        return str(formula.get("U_w_data_status") or "unknown")

    def regen_energy_kWh_from_current_A_s(self, current_times_a_s: float) -> Optional[float]:
        """按式(72) 由 Σ(I_z·t) 折算再生电量（kWh）。

        ``current_times_a_s`` 为 Σ(I_z[A] × t[秒])。式(72) 原式为
        Q_z = U_w·Σ(I_z·t_z)/60（t_z 单位分钟），换成秒后为 U_w·Σ(I_z·t_s)/3600。
        """

        u_w = self.regen_network_voltage_kV()
        if u_w is None:
            return None
        return u_w * current_times_a_s / 3600.0

    @property
    def regen_energy_formula(self) -> dict:
        """再生电量公式（8.6 节式72）及 U_w 取值说明。"""

        return getattr(self, "_regen_formula", {})


_DEFAULT_BANK_CACHE: Optional["LocomotiveCurveBank"] = None


def default_curve_bank() -> "LocomotiveCurveBank":
    """返回使用项目默认数据路径的曲线库单例。

    曲线库在仿真热路径里被每步查询，必须缓存，否则每步都会重新读取并解析 JSON。
    若运行期需要重新加载曲线数据，调用 :func:`reset_curve_bank_cache`。
    """

    global _DEFAULT_BANK_CACHE
    if _DEFAULT_BANK_CACHE is None:
        _DEFAULT_BANK_CACHE = LocomotiveCurveBank()
    return _DEFAULT_BANK_CACHE


def reset_curve_bank_cache() -> None:
    """清空默认曲线库缓存（测试或运行期热加载时使用）。"""

    global _DEFAULT_BANK_CACHE
    _DEFAULT_BANK_CACHE = None


def use_snapshot_curve_bank(path: Path) -> None:
    """Bind the serial solver process to this input snapshot, including absent legacy curves."""
    global _DEFAULT_BANK_CACHE
    _DEFAULT_BANK_CACHE = LocomotiveCurveBank(Path(path))
