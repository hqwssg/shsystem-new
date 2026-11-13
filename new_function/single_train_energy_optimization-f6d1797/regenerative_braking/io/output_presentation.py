"""仅供结果展示使用的中文标签、字段词典与绘图字体。

机读键名（CSV 表头、JSON 字段、NPZ 键）一律保持英文原样，中文只出现在
说明层：本模块把「键名 → 中文名（单位）」集中成唯一来源，供运行说明、
统计报告与文档渲染共用，避免各出口各写一份词表而漏字段。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence


def profile_label(value: str) -> str:
    """展示预设配置的中文名称，保留自定义配置的原始标识以便追溯。"""
    return {"default": "默认", "balanced": "均衡", "robust": "稳健"}.get(value, value)


def status_label(value: str) -> str:
    """将报告状态译成中文，结构化文件中的状态标识仍由调用方保留。"""
    return {
        "not_qualified": "未通过资格验收",
        "training_only": "仅完成训练试验",
        "qualified_on_declared_pilot_only": "仅通过已声明的局部试验",
        "qualified_for_declared_closing_matrix": "通过已声明的收尾矩阵",
        "waiting_for_official_timing": "等待正式运行时分",
        "requires_explicit_timing_manifest": "需要明确确认的时分清单",
        "completed": "已完成",
        "complete": "已完成",
        "running": "正在运行",
        "incomplete": "未完成",
    }.get(value, f"状态标识：{value}")


def verdict_label(value: bool | None) -> str:
    """用于报告正文中的三态判定。"""
    return "通过" if value is True else "未通过" if value is False else "尚未判定"


def comparison_label(value: str) -> str:
    """配对报告使用中文方案名称，结构化键名由调用方保留。"""
    return {"baseline": "基线", "optimized": "优化方案"}.get(value, value)


def train_type_label(value: str) -> str:
    """报告中的车型名称，机读车型枚举保持不变。"""
    return {"Heavy": "重车", "Empty": "空车"}.get(value, value)


def scenario_label(value: str) -> str:
    """解释节能速度曲线报告的时分和质量实验编号。"""
    if value == "runtime_free":
        return "不限定目标运行时分"
    if value.startswith("runtime_") and value.endswith("x"):
        return f"目标运行时分为基线的{value[8:-1]}倍"
    if value.startswith("mass_") and value.endswith("x"):
        return f"列车质量为标称值的{value[5:-1]}倍"
    return value


#: 比较门禁与配对报告字段：不出现在指标表列里，故不并入 FIELD_GLOSSARY
GATE_FIELD_LABELS: dict[str, str] = {
    "physical_violation": "物理约束",
    "closure_failure": "能量闭合",
    "health_failure": "辨识健康",
    "soc_exit_failure": "荷电状态许可退出",
    "runtime_s": "运行时分",
    "traction_energy_kwh": "牵引能量",
    "storage_accepted_energy_kwh": "储能端实际吸收能量",
    "storage_net_of_grid_import_energy_kwh": "扣除回吸后的净存入能量",
}


def field_label(value: str) -> str:
    """解释比较门禁与能量字段，不替换机读字段。"""
    if value in GATE_FIELD_LABELS:
        return GATE_FIELD_LABELS[value]
    return FIELD_GLOSSARY.get(value, (value, ""))[0]


def display_value(value: object) -> str:
    """中文报告中的空值和布尔值；数值不参与重新计算。"""
    if value is None:
        return "未记录"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


# ------------------------------------------------------------------
# 字段词典：键名 -> （中文名，单位或口径）
# ------------------------------------------------------------------
#
# 覆盖两类输出表的全部列：
#   * summary.csv / summary.json —— 场景 × 控制器的指标表
#   * timeseries_*.csv          —— 逐步记录
# 新增指标时只在本表补一条，运行说明与统计报告自动带出，不必各改一处。

#: 标识与元数据
_IDENTITY: dict[str, tuple[str, str]] = {
    "scenario_id": ("场景编号", "机读标识，如 s1_flat_braking"),
    "scenario": ("场景与变体编号", "机读标识，如 s1_flat_braking[nominal]"),
    "scenario_family": ("场景族", "1–10 族编号，机读标识"),
    "scenario_variant": ("场景变体", "nominal、noise_5pct 等，机读标识"),
    "baseline": ("控制器标识", "机读键，主算法为 rhonn_nsmc"),
    "baseline_label": ("控制器标识（本入口）", "机读键，与 baseline 同义"),
    "controller": ("控制器名称", "机读键"),
    "is_optimized": ("是否优化方案", "布尔值"),
    "result_kind": ("结果类别", "机读状态码，标明为仿真结果"),
    "steps": ("积分步数", "步"),
    "duration_s": ("仿真时长", "秒"),
    "filter_mode": ("滤波器模式", "本场景选用的 EKF 或 UKF"),
    "filter_final_mode": ("滤波器终态模式", "运行结束时的选择结果"),
    "filter_switch_count": ("滤波器切换次数", "次"),
    "filter_pending_scheme_confirmation": ("滤波器待确认标识", "原样保留的机读状态"),
    "notes": ("备注", "中文说明，逐条以竖线分隔"),
}

#: 能量口径
_ENERGY: dict[str, tuple[str, str]] = {
    "mechanical_braking_energy_kWh": ("机械制动能量", "千瓦时，轮周口径"),
    "available_regenerative_energy_kWh": ("可再生能量", "千瓦时，电机侧电功率积分"),
    "captured_energy_kWh": ("储能端吸收能量", "千瓦时，尚未扣除储能充电损耗"),
    "storage_energy_kWh": ("储能净存入能量", "千瓦时，逐拍储能能量增量之和"),
    "loss_energy_kWh": ("未存入能量（旧口径）", "千瓦时，含回网能量，不能当作发热耗散"),
    "friction_braking_energy_kWh": ("摩擦制动能量", "千瓦时"),
    "motor_loss_energy_kWh": ("电机损耗能量", "千瓦时，可再生能量减电机电功率"),
    "converter_loss_energy_kWh": ("变流器损耗能量", "千瓦时，开关与导通损耗"),
    "converter_inductor_loss_energy_kWh": ("电感铜损能量", "千瓦时"),
    "storage_loss_energy_kWh": ("储能内部损耗能量", "千瓦时"),
    "curtailed_energy_kWh": ("被削减能量", "千瓦时，储能拒收部分"),
    "grid_export_energy_kWh": ("回网能量", "千瓦时，经母线送回牵引网"),
    "grid_import_energy_kWh": ("电网回吸能量", "千瓦时，从牵引网取电"),
    "grid_net_export_energy_kWh": ("净回网能量", "千瓦时，回网减回吸"),
    "grid_source_loss_energy_kWh": ("源阻抗损耗能量", "千瓦时"),
    "reactive_energy_delta_kWh": ("电抗能量变化", "千瓦时，电感与电容储能净变化"),
    "closure_residual_kWh": ("能量闭合残差", "千瓦时，应接近零"),
    "closure_relative_residual": ("相对闭合残差", "无量纲，闭合残差除以机械制动能量"),
    "regenerative_efficiency": ("再生效率", "无量纲，(储能吸收 − 电网回吸) ÷ 电机侧电功率；扣除回吸部分，避免低速再生不足时出现大于 1"),
    "capture_ratio": ("捕获比例", "无量纲，(储能吸收 − 电网回吸) ÷ 机械制动能量"),
    "regen_current_energy_kWh": (
        "式(72) 电流积分再生电量",
        "千瓦时，Q_z = U_w·Σ(I_z·λ·Δt)，查标准附录 L 的再生电流表；"
        "与「力 × 速度 × 效率」完全独立，仅作互校，不进入能量闭合",
    ),
    "regen_current_charge_a_s": ("式(72) 电流积分量", "安培·秒，Σ I_z·λ·Δt，乘网压后折算电量"),
    "regen_current_to_motor_ratio": (
        "式(72) 与力-速度路径之比",
        "无量纲，电流积分电量 ÷ 电机侧电能量；接近 1 说明两条口径自洽，"
        "大于 1 表示标准电流表隐含的电功率高于本模型的效率假设",
    ),
    "regen_current_check_passed": ("式(72) 交叉校核通过", "布尔值，两路径相对偏差在 ±10% 内；未产生再生电量时为空"),
    "regen_current_implied_efficiency": (
        "标准电流表隐含效率",
        "无量纲，式(72) 电量 ÷ 轮周再生能量；只反映 B_d(v)、I_z(v) 与 U_w 三者是否自洽，与电机效率假设无关。"
        "大于 1 说明网压与电流表原本的绘制电压不一致",
    ),
    "net_storage_capture_ratio": ("净存入捕获比例", "无量纲，净存入能量除以可再生能量"),
    "storage_net_of_grid_import_energy_kWh": ("扣除回吸的净存入能量", "千瓦时，保守口径"),
    "storage_net_of_grid_import_ratio": ("扣除回吸的净存入比例", "无量纲，除以机械制动能量"),
    "reference_section_distance_km": ("参照区间长度", "公里，官方站表里程差；描述整段区间，不是本场景跑过的距离"),
    "reference_official_run_time_min": ("参照区间官方时分", "分钟，PDF 运行图技术资料 2 万吨列车该方向通通时分；整段区间，不可与本场景用时相减"),
    "reference_meter_regen_kwh_per_km_p50": ("参照区间实绩再生强度中位", "千瓦时每公里，智能电表台账该区间 ≥2 万吨列车的单位里程反馈电量中位"),
    "reference_meter_regen_kwh_per_km_p90": ("参照区间实绩再生强度九十分位", "千瓦时每公里，同上口径的 90 分位"),
    "reference_meter_samples": ("参照区间样本数", "条，参与该区间分位数统计的电表台账记录数"),
    "stored_plus_net_grid_export_energy_kWh": ("净存入加净回网能量", "千瓦时"),
    "nonstored_energy_kWh": ("未存入能量", "千瓦时，含回网，不能当作发热耗散"),
    "physical_dissipation_energy_kWh": ("模型显式耗散能量", "千瓦时，摩擦、电机、变流器、电感、源阻抗与储能损耗之和"),
    "regenerative_chain_loss_energy_kWh": ("再生链损耗能量", "千瓦时，显式耗散扣除摩擦制动"),
    "soc_start": ("初始荷电状态", "无量纲，0–1"),
    "soc_end": ("结束荷电状态", "无量纲，0–1"),
    "soc_min_seen": ("过程最低荷电状态", "无量纲，0–1"),
    "soc_max_seen": ("过程最高荷电状态", "无量纲，0–1"),
    "soc_variation": ("荷电状态波动幅度", "无量纲，最高减最低"),
}

#: 波动指标：前缀 × 后缀组合，避免逐条重复
_RIPPLE_PREFIX: dict[str, tuple[str, str]] = {
    "voltage_ripple": ("储能侧电压波动", "伏"),
    "current_ripple": ("储能侧电流波动", "安"),
    "inductor_current_ripple": ("电感电流波动", "安"),
    "input_current_ripple": ("母线电流波动", "安"),
    "input_voltage_ripple": ("母线电压波动", "伏"),
    "power_ripple": ("储能侧功率波动", "瓦"),
}

_RIPPLE_SUFFIX: dict[str, str] = {
    "mean": "均值",
    "std": "标准差",
    "peak_to_peak": "峰峰值",
    "rms": "相对均值的均方根",
    "relative_ripple": "相对波动率，无量纲",
}

#: 跟踪与控制
_CONTROL: dict[str, tuple[str, str]] = {
    "tracking_rmse": ("跟踪均方根误差", "瓦，参考与实测同侧"),
    "tracking_iae": ("跟踪绝对误差积分", "瓦·秒"),
    "tracking_ise": ("跟踪平方误差积分", "瓦²·秒"),
    "tracking_max_abs_error": ("跟踪最大绝对误差", "瓦"),
    "tracking_final_abs_error": ("跟踪末端绝对误差", "瓦"),
    "settling_time": ("调节时间", "秒，进入稳态带所需时间"),
    "overshoot": ("超调比例", "无量纲，相对参考均值"),
    "control_effort_tv": ("占空比总变差", "无量纲，抖振指标，不是损耗能量"),
    "control_effort_rate": ("占空比变化率", "每秒，总变差除以时长"),
    "duty_saturation_ratio": ("占空比贴轨比例", "无量纲，按实际生效可行域判定"),
    "converter_over_rating_ratio": ("变流器超额定功率比例", "无量纲，超过额定功率的样本占比"),
    "converter_input_current_over_limit_ratio": ("变流器超输入电流上限比例", "无量纲"),
}

#: 逐步记录
_TIMESERIES: dict[str, tuple[str, str]] = {
    "time_s": ("仿真时间", "秒"),
    "speed_mps": ("车速", "米每秒"),
    "mechanical_braking_power_w": ("机械制动功率", "瓦，轮周口径"),
    "regen_wheel_power_w": ("可再生机械功率", "瓦，轮周口径"),
    "friction_braking_power_w": ("摩擦制动功率", "瓦"),
    "motor_electrical_power_w": ("电机电功率", "瓦，折算到直流侧"),
    "duty_cycle_T1": ("上管占空比 T1", "无量纲，受 0–0.9 约束"),
    "duty_cycle_T2": ("下管占空比 T2", "无量纲，受 0–0.9 约束"),
    "input_voltage_v": ("母线电压", "伏"),
    "input_current_a": ("母线电流", "安"),
    "inductor_current_a": ("电感电流", "安"),
    "output_voltage_v": ("储能侧电压", "伏"),
    "output_current_a": ("储能侧电流", "安"),
    "output_power_w": ("储能侧输出功率", "瓦"),
    "reference_power_w": ("参考可吸收功率", "瓦，储能侧，与实测同侧"),
    "accepted_power_w": ("储能实际接受功率", "瓦"),
    "curtailed_power_w": ("被削减功率", "瓦"),
    "grid_export_power_w": ("回网功率", "瓦"),
    "grid_import_power_w": ("电网回吸功率", "瓦"),
    "grid_source_loss_w": ("源阻抗损耗功率", "瓦"),
    "soc": ("荷电状态", "无量纲，0–1"),
    "motor_efficiency": ("电机再生效率", "无量纲"),
    "dc_link_derating": ("母线过压降额系数", "无量纲，1 表示不降额"),
    "stored_energy_delta_j": ("本拍储能能量增量", "焦耳"),
    "storage_loss_j": ("本拍储能损耗", "焦耳"),
    "converter_loss_power_w": ("本拍变流器损耗功率", "瓦"),
    "converter_inductor_loss_power_w": ("本拍电感铜损功率", "瓦"),
    "reactive_energy_delta_j": ("电抗能量变化", "焦耳"),
    "storage_charge_power_limit_w": ("储能充电功率上限", "瓦，同拍许可值"),
    "control_update": ("控制是否更新", "0 或 1"),
    "charge_safety_override": ("充电安全覆盖是否生效", "0 或 1"),
}


def _with_ripples() -> dict[str, tuple[str, str]]:
    merged: dict[str, tuple[str, str]] = {}
    for prefix, (name, unit) in _RIPPLE_PREFIX.items():
        for suffix, suffix_name in _RIPPLE_SUFFIX.items():
            merged[f"{prefix}_{suffix}"] = (f"{name}{suffix_name}", unit)
    return merged


#: 公开词典：键名 -> （中文名，单位或口径）
FIELD_GLOSSARY: dict[str, tuple[str, str]] = {
    **_IDENTITY,
    **_ENERGY,
    **_with_ripples(),
    **_CONTROL,
    **_TIMESERIES,
}

#: 逐步记录的列顺序，供运行说明按实际写入顺序展开
TIMESERIES_FIELDS: tuple[str, ...] = tuple(_TIMESERIES)


def field_glossary(key: str) -> tuple[str, str]:
    """返回单个键的中文名与单位；未登记时退回键名本身并显式标注。"""
    return FIELD_GLOSSARY.get(key, (key, "尚未登记中文释义"))


def glossary_lines(keys: Iterable[str]) -> list[str]:
    """把键序列渲染成 Markdown 词表条目，保持传入顺序并去重。"""
    lines: list[str] = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        name, unit = field_glossary(key)
        lines.append(f"- `{key}`：{name}（{unit}）")
    return lines


def undocumented_fields(keys: Iterable[str]) -> list[str]:
    """列出词典未覆盖的键，供专项测试守住「新增指标必须登记」。"""
    return [key for key in keys if key not in FIELD_GLOSSARY]


def glossary_coverage(keys: Sequence[str]) -> float:
    """已登记键的占比，用于报告或测试断言。"""
    if not keys:
        return 1.0
    return sum(1 for key in keys if key in FIELD_GLOSSARY) / len(keys)


def configure_chinese_plotting() -> str:
    """为结果图选择已安装的中文字体，避免中文标签被绘制为方框。"""
    import matplotlib
    from matplotlib import font_manager

    names = {font.name for font in font_manager.fontManager.ttflist}
    candidates = ("Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC",
                  "Source Han Sans SC", "WenQuanYi Micro Hei", "Arial Unicode MS")
    selected = next((name for name in candidates if name in names), None)
    if selected is None:
        raise RuntimeError("结果图需要中文字体，请先安装微软雅黑、宋体或思源黑体等中文字体")
    matplotlib.rcParams.update({"font.family": "sans-serif", "font.sans-serif": [selected],
                               "axes.unicode_minus": False})
    return selected
