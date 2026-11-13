"""参数字段的中文名、单位与溯源措辞。

单一来源约定：参数字段的中文名、单位推断、可上屏的溯源表述都只在这里定义。
交付包构建脚本与数据库投影层都从这里取，避免出现两套译名。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: 参数字段中文名，逐字段登记（61 个数值字段）。
#: 新增参数字段必须在此补一条；`regenerative_braking.database` 导入时会校验覆盖率。
PARAMETER_FIELD_CN: dict[str, str] = {
    # ---- 列车 ----
    "mass_kg": "列车质量",
    "vehicle_mass_tons": "车辆总重（不含机车）",
    "locomotive_type": "机车机型",
    "locomotive_count": "机车台数",
    "electrical_level": "电制动投入级位",
    "train_length_m": "列车长度",
    "longitudinal_segments": "纵向离散段数",
    "rotational_mass_factor": "旋转质量系数",
    "max_brake_force_n": "最大制动力",
    "max_regen_force_n": "最大再生制动力",
    "regen_fraction_cap": "再生制动占比上限",
    "basic_resistance.a_n_per_kn": "基本阻力常数项",
    "basic_resistance.b_n_per_kn_per_kmh": "基本阻力速度一次项",
    "basic_resistance.c_n_per_kn_per_kmh2": "基本阻力速度二次项",
    "basic_resistance.curve_equivalent_per_mille_numerator": "曲线附加阻力等效分子",
    "adhesion.coefficient": "黏着系数",
    "adhesion.braking_safety_factor": "制动黏着安全系数",
    "gravity_m_per_s2": "重力加速度",
    "ambient.rolling_multiplier": "滚动阻力环境修正系数",
    "ambient.aerodynamic_multiplier": "气动阻力环境修正系数",
    # ---- 电机 ----
    "max_regen_power_w": "最大再生电功率",
    "regen_efficiency.peak": "电机峰值效率",
    "regen_efficiency.peak_load_ratio": "峰值负载归一化点",
    "regen_efficiency.low_load_penalty": "轻载效率惩罚",
    "regen_efficiency.low_speed_penalty": "低速效率惩罚",
    "regen_efficiency.low_speed_reference_m_per_s": "低速惩罚参考速度",
    "min_regen_speed_m_per_s": "最低可再生速度",
    "dc_link_voltage_window.min_v": "直流母线电压下限",
    "dc_link_voltage_window.nominal_v": "直流母线额定电压",
    "dc_link_voltage_window.max_v": "直流母线电压上限",
    "overvoltage_derate_start_v": "过压降额起始电压",
    "overvoltage_derate_end_v": "过压降额终止电压",
    # ---- 变流器 ----
    "duty_limit.u0_max": "占空比上限",
    "duty_limit.min": "占空比下限",
    "duty_limit.max": "占空比物理上限",
    "inductance_h": "滤波电感",
    "inductor_resistance_ohm": "电感等效电阻",
    "input_capacitance_f": "母线侧输入电容",
    "output_capacitance_f": "储能侧输出电容",
    "switching_frequency_hz": "开关频率",
    "dc_bus_source.open_circuit_voltage_v": "母线源开路电压",
    "dc_bus_source.resistance_ohm": "母线源内阻",
    "converter_efficiency": "变流器效率",
    "power_rating_w": "变流器额定功率",
    "max_input_current_a": "最大输入电流",
    "max_output_current_a": "最大输出电流",
    "input_voltage_window.min_v": "母线电压窗口下限",
    "input_voltage_window.nominal_v": "母线电压窗口额定值",
    "input_voltage_window.max_v": "母线电压窗口上限",
    "output_voltage_window.min_v": "储能侧电压窗口下限",
    "output_voltage_window.nominal_v": "储能侧电压窗口额定值",
    "output_voltage_window.max_v": "储能侧电压窗口上限",
    # ---- 储能 ----
    "capacity_j": "储能容量（焦耳）",
    "capacity_kwh": "储能容量",
    "round_trip_efficiency": "往返效率",
    "charge_efficiency": "充电效率",
    "discharge_efficiency": "放电效率",
    "soc_min": "SOC 下限",
    "soc_max": "SOC 上限",
    "soc_initial": "初始 SOC",
    "max_charge_power_w": "最大充电功率",
    "max_discharge_power_w": "最大放电功率",
    "nominal_voltage_v": "储能额定电压",
    "internal_resistance_ohm": "储能内阻",
}

#: 单位推断表：按后缀长度降序匹配，保证 `_m_per_s` 不被 `_s` 抢先命中
_UNIT_SUFFIX: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "_n_per_kn_per_kmh2": "N/(kN·km/h²)",
            "_n_per_kn_per_kmh": "N/(kN·km/h)",
            "_n_per_kn": "N/kN",
            "_per_mille_numerator": "‰",
            "_m_per_s2": "m/s²",
            "_m_per_s": "m/s",
            "_kwh": "kWh",
            "_kg": "kg",
            "_tons": "t",
            "_kw": "kW",
            "_mw": "MW",
            "_kmh": "km/h",
            "_hz": "Hz",
            "_ohm": "Ω",
            "_ms": "ms",
            "_mm": "mm",
            "_km": "km",
            "_m": "m",
            "_s": "s",
            "_v": "V",
            "_a": "A",
            "_w": "W",
            "_j": "J",
            "_h": "H",
            "_f": "F",
            "_n": "N",
            "_ratio": "—",
            "_factor": "—",
            "_fraction": "—",
            "_cap": "—",
            "_count": "个",
            "_segments": "段",
            "_steps": "拍",
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

#: 内部溯源措辞 -> 可直接上屏的工程表述（按顺序逐条替换）
_DISPLAY_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("占位包络", "解析包络"),
    ("工程预设包络", "解析包络"),
    ("占位：待", "工程预设，待"),
    ("占位", "工程预设"),
    ("placeholder", "工程预设"),
    ("工程虚拟预设", "工程预设"),
    ("到位后替换", "确认"),
    ("后替换", "确认"),
    ("非实测特性曲线", "非实测曲线"),
)

#: 参数文件元信息键，不属于数值字段
META_KEYS = frozenset(
    {
        "schema_version",
        "profile_id",
        "label",
        "data_status",
        "note",
        "field_data_status",
        "provenance",
    }
)


def unit_of(field_path: str) -> str:
    """从字段名后缀推断单位；无匹配返回空串（表示无量纲或未标注）。"""

    for suffix, unit in _UNIT_SUFFIX:
        if field_path.endswith(suffix):
            return unit
    return ""


def display_text(text: str) -> str:
    """把内部溯源措辞改写为可直接上界面的工程表述。"""

    if not text:
        return ""
    result = text
    for source, target in _DISPLAY_REPLACEMENTS:
        result = result.replace(source, target)
    return result


def lookup(table: Mapping[str, str], field_path: str) -> str:
    """精确匹配优先，其次取最长的父级键（支持 `a.b` 形式的嵌套字段）。"""

    if field_path in table:
        return table[field_path]
    candidates = [key for key in table if field_path.startswith(key + ".")]
    if not candidates:
        return ""
    return table[max(candidates, key=len)]


def is_numeric_field(value: Any) -> bool:
    """数值标量，或全为数值的列表。"""

    if isinstance(value, (int, float)):
        return True
    return bool(value) and isinstance(value, list) and all(
        isinstance(item, (int, float)) for item in value
    )


def flatten_parameters(
    payload: Mapping[str, Any], prefix: str = ""
) -> Iterable[tuple[str, Any]]:
    """把参数 payload 展开为 (字段路径, 值)，跳过元信息与文本字段。

    嵌套 dict 用点号连接；数值列表整体保留为一个字段（如 `longitudinal_segments`）。
    """

    for key, value in payload.items():
        if not prefix and key in META_KEYS:
            continue
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from flatten_parameters(value, path + ".")
        elif is_numeric_field(value):
            yield path, value
