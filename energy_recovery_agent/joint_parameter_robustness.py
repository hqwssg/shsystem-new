"""参数区间与运行扰动的联合稳健性场景定义和参数变换。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from random import Random
from typing import Any, Mapping, Sequence
import json
import math

from power_arm_electrical_limits import PowerArmElectricalLimit
from train_simulator import BatteryStorageParameters, DavisCoefficients, TrainParameters


ALLOWED_FACTOR_NAMES = (
    "heavy_mass",
    "empty_mass",
    "davis_a",
    "davis_b",
    "davis_c",
    "max_traction",
    "max_brake",
    "max_power",
    "storage_capacity",
    "storage_charge_power",
    "storage_discharge_power",
    "storage_efficiency",
    "electrical_traction_supply",
    "electrical_regen_absorption",
    "electrical_grid_feedback",
)

# 用于构造物理意义上的不利角点。质量和阻力增大通常不利，其余能力参数减小通常不利。
ADVERSE_BOUND = {
    "heavy_mass": "upper",
    "empty_mass": "upper",
    "davis_a": "upper",
    "davis_b": "upper",
    "davis_c": "upper",
    "max_traction": "lower",
    "max_brake": "lower",
    "max_power": "lower",
    "storage_capacity": "lower",
    "storage_charge_power": "lower",
    "storage_discharge_power": "lower",
    "storage_efficiency": "lower",
    "electrical_traction_supply": "lower",
    "electrical_regen_absorption": "lower",
    "electrical_grid_feedback": "lower",
}


@dataclass(frozen=True)
class FactorRange:
    """相对名义值的闭区间。"""

    lower: float
    upper: float

    def __post_init__(self) -> None:
        for name in ("lower", "upper"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"参数因子{name}必须是有限正数。")
            object.__setattr__(self, name, float(value))
        if self.lower > 1.0 or self.upper < 1.0 or self.lower > self.upper:
            raise ValueError("参数因子区间必须满足 lower <= 1 <= upper。")


@dataclass(frozen=True)
class JointParameterScenario:
    """一次联合物理参数取值。"""

    scenario_id: str
    design_role: str
    factors: Mapping[str, float]


@dataclass(frozen=True)
class JointRangeConfig:
    """联合稳健性评价合同。"""

    schema_version: str
    evaluation_code: str
    data_status: str
    ranges: Mapping[str, FactorRange]
    interior_sample_count: int = 4
    seed: int = 20260908


def load_joint_range_config(path: Path) -> JointRangeConfig:
    """读取并严格校验参数区间 JSON。"""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("联合参数区间文件根节点必须是JSON对象。")
    required = {"schema_version", "evaluation_code", "data_status", "ranges"}
    missing = required - set(payload)
    unknown = set(payload) - required - {"sampling"}
    if missing or unknown:
        raise ValueError(f"联合参数区间字段不合法；缺失={sorted(missing)}，未知={sorted(unknown)}。")
    if str(payload["schema_version"]) != "1.0":
        raise ValueError("当前仅支持联合参数区间 schema_version=1.0。")
    raw_ranges = payload["ranges"]
    if not isinstance(raw_ranges, dict) or not raw_ranges:
        raise ValueError("ranges必须是非空JSON对象。")
    unknown_ranges = set(raw_ranges) - set(ALLOWED_FACTOR_NAMES)
    if unknown_ranges:
        raise ValueError(f"存在不支持的参数区间：{sorted(unknown_ranges)}。")
    ranges: dict[str, FactorRange] = {}
    for name, bounds in raw_ranges.items():
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"ranges.{name}必须是[lower, upper]。")
        ranges[name] = FactorRange(bounds[0], bounds[1])
    sampling = payload.get("sampling", {})
    if not isinstance(sampling, dict) or set(sampling) - {"interior_sample_count", "seed"}:
        raise ValueError("sampling仅允许interior_sample_count和seed。")
    count = sampling.get("interior_sample_count", 4)
    seed = sampling.get("seed", 20260908)
    if isinstance(count, bool) or int(count) != count or int(count) < 0:
        raise ValueError("interior_sample_count必须是非负整数。")
    if isinstance(seed, bool) or int(seed) != seed or int(seed) < 0:
        raise ValueError("seed必须是非负整数。")
    return JointRangeConfig(
        schema_version="1.0",
        evaluation_code=str(payload["evaluation_code"]).strip(),
        data_status=str(payload["data_status"]).strip(),
        ranges=ranges,
        interior_sample_count=int(count),
        seed=int(seed),
    )


def config_sha256(path: Path) -> str:
    """计算区间合同原文件摘要。"""

    return sha256(Path(path).read_bytes()).hexdigest()


def build_joint_parameter_scenarios(config: JointRangeConfig) -> list[JointParameterScenario]:
    """生成可复现的边界覆盖和拉丁超立方内部样本。"""

    names = sorted(config.ranges)
    nominal = {name: 1.0 for name in names}
    candidates: list[tuple[str, str, dict[str, float]]] = [("P000", "nominal", nominal)]

    def boundary(use_adverse: bool) -> dict[str, float]:
        values = {}
        for name in names:
            interval = config.ranges[name]
            adverse_side = ADVERSE_BOUND[name]
            side = adverse_side if use_adverse else ("lower" if adverse_side == "upper" else "upper")
            values[name] = getattr(interval, side)
        return values

    candidates.extend([
        ("P001", "directed_adverse_corner", boundary(True)),
        ("P002", "directed_favorable_corner", boundary(False)),
        ("P003", "all_lower_corner", {name: config.ranges[name].lower for name in names}),
        ("P004", "all_upper_corner", {name: config.ranges[name].upper for name in names}),
    ])
    sequence = 5
    for name in names:
        for side in ("lower", "upper"):
            values = dict(nominal)
            values[name] = getattr(config.ranges[name], side)
            candidates.append((f"P{sequence:03d}", f"single_{name}_{side}", values))
            sequence += 1

    # 每一维独立打乱分层编号，形成固定种子的拉丁超立方样本。
    rng = Random(config.seed)
    count = config.interior_sample_count
    permutations: dict[str, list[int]] = {}
    for name in names:
        cells = list(range(count))
        rng.shuffle(cells)
        permutations[name] = cells
    for sample_index in range(count):
        values = {}
        for name in names:
            interval = config.ranges[name]
            unit = (permutations[name][sample_index] + rng.random()) / count
            values[name] = interval.lower + unit * (interval.upper - interval.lower)
        candidates.append((f"P{sequence:03d}", "latin_hypercube_interior", values))
        sequence += 1

    # 退化区间可能令不同设计点完全相同；按取值去重并保留最先出现的可解释角色。
    unique: list[JointParameterScenario] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for scenario_id, role, values in candidates:
        key = tuple((name, round(values[name], 12)) for name in names)
        if key in seen:
            continue
        seen.add(key)
        unique.append(JointParameterScenario(scenario_id, role, values))
    return unique


def apply_train_factors(
    trains: Mapping[str, TrainParameters], factors: Mapping[str, float]
) -> dict[str, TrainParameters]:
    """把质量、戴维斯阻力和牵引制动能力因子应用到列车参数。"""

    result: dict[str, TrainParameters] = {}
    for key, train in trains.items():
        mass_factor = factors.get("heavy_mass" if key == "Heavy" else "empty_mass", 1.0)
        updated_mass = train.mass_tons * mass_factor
        result[key] = replace(
            train,
            mass_tons=updated_mass,
            mass_min_tons=min(train.mass_min_tons or updated_mass, updated_mass),
            mass_max_tons=max(train.mass_max_tons or updated_mass, updated_mass),
            mass_data_status="joint_interval_scenario",
            mass_note="联合参数区间稳健性评价取值。",
            max_traction_kN=train.max_traction_kN * factors.get("max_traction", 1.0),
            max_brake_kN=train.max_brake_kN * factors.get("max_brake", 1.0),
            max_power_kW=train.max_power_kW * factors.get("max_power", 1.0),
            # 同上：consist 生效时功率上限来自特性表，倍率必须写进 power_scale。
            power_scale=train.power_scale * factors.get("max_power", 1.0),
            davis=DavisCoefficients(
                train.davis.a * factors.get("davis_a", 1.0),
                train.davis.b * factors.get("davis_b", 1.0),
                train.davis.c * factors.get("davis_c", 1.0),
            ),
        )
    return result


def apply_battery_factors(
    battery: BatteryStorageParameters, factors: Mapping[str, float]
) -> BatteryStorageParameters:
    """按SOC比例不变原则缩放聚合或逐设备储能参数。"""

    capacity_factor = factors.get("storage_capacity", 1.0)
    charge_factor = factors.get("storage_charge_power", 1.0)
    discharge_factor = factors.get("storage_discharge_power", 1.0)
    efficiency_factor = factors.get("storage_efficiency", 1.0)
    devices = []
    for device in battery.storage_devices:
        devices.append(replace(
            device,
            capacity_kwh=device.capacity_kwh * capacity_factor,
            max_charge_power_kw=device.max_charge_power_kw * charge_factor,
            max_discharge_power_kw=device.max_discharge_power_kw * discharge_factor,
            charge_efficiency=min(1.0, device.charge_efficiency * math.sqrt(efficiency_factor)),
            discharge_efficiency=min(1.0, device.discharge_efficiency * math.sqrt(efficiency_factor)),
            initial_soc_kwh=device.initial_soc_kwh * capacity_factor,
            min_soc_kwh=device.min_soc_kwh * capacity_factor,
            max_soc_kwh=float(device.max_soc_kwh) * capacity_factor,
            data_status="joint_interval_scenario",
            source_note="联合参数区间稳健性评价取值。",
        ))
    return replace(
        battery,
        capacity_kwh=battery.capacity_kwh * capacity_factor,
        max_charge_power_kW=battery.max_charge_power_kW * charge_factor,
        max_discharge_power_kW=battery.max_discharge_power_kW * discharge_factor,
        round_trip_efficiency=min(1.0, battery.round_trip_efficiency * efficiency_factor),
        storage_devices=tuple(devices),
        data_status="joint_interval_scenario",
        scenario_name="joint_parameter_robustness",
        planning_assumption=True,
        note="联合参数区间稳健性评价取值；不替代正式设备参数。",
    )


def apply_electrical_factors(
    limits: Mapping[str, PowerArmElectricalLimit], factors: Mapping[str, float]
) -> dict[str, PowerArmElectricalLimit]:
    """缩放供电、再生吸收和反馈上限。"""

    return {
        key: replace(
            value,
            max_traction_supply_kw=value.max_traction_supply_kw
            * factors.get("electrical_traction_supply", 1.0),
            max_regen_absorption_kw=value.max_regen_absorption_kw
            * factors.get("electrical_regen_absorption", 1.0),
            max_grid_feedback_kw=value.max_grid_feedback_kw
            * factors.get("electrical_grid_feedback", 1.0),
            electrical_limit_status="joint_interval_scenario",
            electrical_limit_note="联合参数区间稳健性评价取值。",
        )
        for key, value in limits.items()
    }


def scenario_parameter_rows(
    scenarios: Sequence[JointParameterScenario], config: JointRangeConfig
) -> list[dict[str, Any]]:
    """转换为长表，便于数据库和表格软件展示。"""

    rows = []
    for scenario in scenarios:
        for name in sorted(config.ranges):
            interval = config.ranges[name]
            rows.append({
                "parameter_scenario_id": scenario.scenario_id,
                "design_role": scenario.design_role,
                "parameter_name": name,
                "lower_factor": interval.lower,
                "nominal_factor": 1.0,
                "upper_factor": interval.upper,
                "applied_factor": round(float(scenario.factors[name]), 9),
            })
    return rows
