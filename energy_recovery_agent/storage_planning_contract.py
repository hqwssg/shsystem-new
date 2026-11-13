"""储能选址定容规划阶段A的数据对象、文件合同、校验和稳定指纹。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
import csv
import json
import math


SCHEMA_VERSION = "1.0"
CONTRACT_FILE_NAMES = (
    "storage_candidate_sites.csv",
    "storage_technologies.csv",
    "storage_site_technology_options.csv",
    "storage_planning_scenarios.json",
    "storage_planning_policy.json",
)
DATA_STATUSES = {"official", "derived_from_official", "planning_placeholder", "synthetic"}
DIRECTIONS = {"forward", "reverse", "both"}
TARGET_FINAL_SOC_RULES = {"cyclic", "not_below_initial", "priced_deviation"}
OBJECTIVE_MODES = {"annualized_cost", "energy_first", "balanced"}
RISK_MEASURES = {"expected", "worst_case", "cvar"}
SOLVER_PROFILES = {"quick", "standard", "fine"}
PARAMETER_OVERRIDE_FIELDS = {
    "heavy_mass_factor",
    "empty_mass_factor",
    "traction_power_factor",
    "brake_power_factor",
    "davis_resistance_factor",
    "storage_efficiency_factor",
    "power_arm_capacity_factor",
    "storage_power_factor",
}


class StoragePlanningContractError(ValueError):
    """表示规划输入文件违反明确的数据合同。"""

    def __init__(self, code: str, file_name: str, field: str, message: str) -> None:
        """保存机器错误码和面向使用者的准确文件位置。"""
        self.code = code
        self.file_name = file_name
        self.field = field
        self.message = message
        super().__init__(f"{file_name}:{field} [{code}] {message}")

    def to_dict(self) -> Dict[str, str]:
        """转换为可写入质量报告的结构化问题。"""
        return {
            "severity": "error",
            "code": self.code,
            "file": self.file_name,
            "field": self.field,
            "message": self.message,
        }


def _fail(code: str, file_name: str, field: str, message: str) -> None:
    """抛出带文件、字段和错误码的合同异常。"""
    raise StoragePlanningContractError(code, file_name, field, message)


def _text(value: Any, file_name: str, field: str, *, required: bool = True) -> str:
    """读取去除首尾空白的文本字段。"""
    text = "" if value is None else str(value).strip()
    if required and not text:
        _fail("required_field_missing", file_name, field, "字段不能为空。")
    return text


def _number(
    value: Any,
    file_name: str,
    field: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    optional: bool = False,
) -> Optional[float]:
    """读取有限数值并执行上下界校验。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        _fail("required_field_missing", file_name, field, "字段不能为空。")
    if isinstance(value, bool):
        _fail("invalid_number", file_name, field, "布尔值不能作为数值。")
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail("invalid_number", file_name, field, f"必须是数值，当前为 {value!r}。")
    if not math.isfinite(number):
        _fail("non_finite_number", file_name, field, "必须是有限数值。")
    if minimum is not None and number < minimum:
        _fail("number_below_minimum", file_name, field, f"必须大于或等于 {minimum}。")
    if maximum is not None and number > maximum:
        _fail("number_above_maximum", file_name, field, f"必须小于或等于 {maximum}。")
    return number


def _integer(
    value: Any,
    file_name: str,
    field: str,
    *,
    minimum: int = 0,
    optional: bool = False,
) -> Optional[int]:
    """读取不允许小数和布尔值的整数。"""
    number = _number(value, file_name, field, minimum=float(minimum), optional=optional)
    if number is None:
        return None
    if not number.is_integer():
        _fail("invalid_integer", file_name, field, "必须是整数。")
    return int(number)


def _boolean(value: Any, file_name: str, field: str) -> bool:
    """严格读取布尔值，不接受容易混淆的任意真值。"""
    if type(value) is bool:
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    _fail("invalid_boolean", file_name, field, "必须为 true 或 false。")


def _enum(value: Any, allowed: set[str], file_name: str, field: str) -> str:
    """读取限定枚举值。"""
    parsed = _text(value, file_name, field)
    if parsed not in allowed:
        _fail("unknown_enum", file_name, field, f"不支持 {parsed!r}，允许值为 {sorted(allowed)}。")
    return parsed


def _optional_positive_step(value: Any, file_name: str, field: str) -> Optional[float]:
    """读取可选的严格正离散步长。"""
    number = _number(value, file_name, field, minimum=0.0, optional=True)
    if number is not None and number <= 0.0:
        _fail("non_positive_step", file_name, field, "离散步长必须大于 0；连续定容请留空。")
    return number


def _check_keys(
    payload: Mapping[str, Any],
    *,
    required: Iterable[str],
    optional: Iterable[str],
    file_name: str,
    field: str,
) -> None:
    """拒绝缺失必需字段和未批准字段。"""
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(payload))
    unknown = sorted(set(payload) - allowed)
    if missing:
        _fail("required_field_missing", file_name, field, f"缺少字段：{missing}。")
    if unknown:
        _fail("unknown_field", file_name, field, f"包含未批准字段：{unknown}。")


def _relative_reference(value: Any, file_name: str, field: str) -> str:
    """校验数据版本内的逻辑相对路径，阻断绝对路径和目录穿越。"""
    reference = _text(value, file_name, field)
    normalized = reference.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _fail("unsafe_relative_path", file_name, field, "必须是无目录穿越的版本内相对路径。")
    return str(path)


@dataclass(frozen=True)
class StorageCandidateSite:
    """可由规划器选择的、已经过外部物理筛选的储能候选位置。"""

    site_code: str
    site_name: str
    position_km: float
    power_arm_code: str
    storage_section_start_km: float
    storage_section_end_km: float
    direction: str
    buildable: bool
    max_connection_power_kw: float
    max_capacity_kwh: float
    fixed_site_cost_cny: float
    allowed_technology_codes: Tuple[str, ...]
    data_status: str
    source_note: str = ""


@dataclass(frozen=True)
class StorageTechnology:
    """可在候选位置安装的一组储能物理和经济参数。"""

    technology_code: str
    technology_name: str
    min_capacity_kwh: float
    max_capacity_kwh: float
    capacity_step_kwh: Optional[float]
    min_charge_power_kw: float
    max_charge_power_kw: float
    charge_power_step_kw: Optional[float]
    min_discharge_power_kw: float
    max_discharge_power_kw: float
    discharge_power_step_kw: Optional[float]
    charge_efficiency: float
    discharge_efficiency: float
    min_soc_ratio: float
    max_soc_ratio: float
    self_discharge_rate_per_hour: float
    calendar_life_years: float
    cycle_life: float
    fixed_device_cost_cny: float
    cost_per_kwh_cny: float
    charge_power_cost_per_kw_cny: float
    discharge_power_cost_per_kw_cny: float
    annual_om_rate: float
    throughput_degradation_cost_per_kwh: float
    data_status: str
    source_note: str = ""


@dataclass(frozen=True)
class StorageSiteTechnologyOption:
    """候选位置与允许技术的关联及站点特有限值。"""

    site_code: str
    technology_code: str
    min_capacity_kwh: Optional[float]
    max_capacity_kwh: Optional[float]
    max_charge_power_kw: Optional[float]
    max_discharge_power_kw: Optional[float]
    max_unit_count: int
    available: bool
    source_note: str = ""


@dataclass(frozen=True)
class StoragePlanningScheduleTemplate:
    """不依赖外部运行图文件的合成重空发车模板。"""

    heavy_count: int
    empty_count: int
    heavy_headway_s: int
    empty_headway_s: int
    heavy_empty_phase_s: int


@dataclass(frozen=True)
class StoragePlanningScenario:
    """一个共享规划设备、但拥有独立运行变量的典型场景。"""

    scenario_code: str
    scenario_name: str
    weight: float
    core_for_feasibility: bool
    timetable_relative_path: Optional[str]
    schedule_template: Optional[StoragePlanningScheduleTemplate]
    grid_price_per_kwh: float
    demand_charge_per_kw_year: float
    wasted_energy_penalty_per_kwh: float
    parameter_overrides: Tuple[Tuple[str, float], ...]
    storage_outage_site_codes: Tuple[str, ...]
    data_status: str
    source_note: str = ""


@dataclass(frozen=True)
class StoragePlanningPolicy:
    """一次规划任务的业务目标、预算、风险和求解资源约束。"""

    policy_code: str
    planning_horizon_years: int
    discount_rate: float
    analysis_days_per_year: int
    max_site_count: int
    total_budget_cny: float
    allow_no_build: bool
    target_final_soc_rule: str
    final_soc_tolerance_kwh: float
    objective_mode: str
    include_demand_charge: bool
    allow_timetable_coordination: bool
    coordination_shortlist_size: int
    core_scenarios_must_all_be_feasible: bool
    risk_measure: str
    cvar_alpha: Optional[float]
    minimum_grid_reduction_kwh: float
    minimum_annual_saving_cny: float
    solver_profile: str
    max_wall_clock_s: int
    seed: int
    data_status: str
    source_note: str = ""


@dataclass(frozen=True)
class StoragePlanningBundle:
    """文件适配器投影出的统一、不可变规划输入。"""

    source_dir: Path
    scenario_set_code: str
    sites: Tuple[StorageCandidateSite, ...]
    technologies: Tuple[StorageTechnology, ...]
    site_technology_options: Tuple[StorageSiteTechnologyOption, ...]
    scenarios: Tuple[StoragePlanningScenario, ...]
    policy: StoragePlanningPolicy
    input_fingerprint_sha256: str
    recommendation_level: str

    def summary(self) -> Dict[str, Any]:
        """返回适合命令行、数据库任务和测试使用的摘要。"""
        status_counts: Dict[str, int] = {}
        statuses = [item.data_status for item in self.sites]
        statuses += [item.data_status for item in self.technologies]
        statuses += [item.data_status for item in self.scenarios]
        statuses.append(self.policy.data_status)
        for status in statuses:
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": True,
            "source_dir": str(self.source_dir),
            "scenario_set_code": self.scenario_set_code,
            "policy_code": self.policy.policy_code,
            "site_count": len(self.sites),
            "buildable_site_count": sum(1 for item in self.sites if item.buildable),
            "technology_count": len(self.technologies),
            "site_technology_option_count": len(self.site_technology_options),
            "scenario_count": len(self.scenarios),
            "core_scenario_count": sum(1 for item in self.scenarios if item.core_for_feasibility),
            "data_status_counts": dict(sorted(status_counts.items())),
            "recommendation_level": self.recommendation_level,
            "input_fingerprint_sha256": self.input_fingerprint_sha256,
        }


SITE_COLUMNS = (
    "site_code", "site_name", "position_km", "power_arm_code",
    "storage_section_start_km", "storage_section_end_km", "direction", "buildable",
    "max_connection_power_kw", "max_capacity_kwh", "fixed_site_cost_cny",
    "allowed_technology_codes", "data_status", "source_note",
)
TECHNOLOGY_COLUMNS = (
    "technology_code", "technology_name", "min_capacity_kwh", "max_capacity_kwh",
    "capacity_step_kwh", "min_charge_power_kw", "max_charge_power_kw",
    "charge_power_step_kw", "min_discharge_power_kw", "max_discharge_power_kw",
    "discharge_power_step_kw", "charge_efficiency", "discharge_efficiency",
    "min_soc_ratio", "max_soc_ratio", "self_discharge_rate_per_hour",
    "calendar_life_years", "cycle_life", "fixed_device_cost_cny", "cost_per_kwh_cny",
    "charge_power_cost_per_kw_cny", "discharge_power_cost_per_kw_cny", "annual_om_rate",
    "throughput_degradation_cost_per_kwh", "data_status", "source_note",
)
OPTION_COLUMNS = (
    "site_code", "technology_code", "min_capacity_kwh", "max_capacity_kwh",
    "max_charge_power_kw", "max_discharge_power_kw", "max_unit_count", "available",
    "source_note",
)


def _read_csv(path: Path, expected_columns: Sequence[str]) -> list[Dict[str, str]]:
    """读取具有冻结表头的非空 UTF-8 CSV。"""
    if not path.is_file():
        _fail("missing_file", path.name, "", "必需文件不存在。")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            actual = tuple(reader.fieldnames or ())
            if actual != tuple(expected_columns):
                _fail(
                    "invalid_header",
                    path.name,
                    "header",
                    f"表头必须精确为 {list(expected_columns)}，当前为 {list(actual)}。",
                )
            rows = list(reader)
    except UnicodeDecodeError:
        _fail("invalid_encoding", path.name, "", "文件必须使用 UTF-8 编码。")
    if not rows:
        _fail("empty_file", path.name, "", "至少需要一行数据。")
    return rows


def _read_json(path: Path) -> Mapping[str, Any]:
    """读取顶层必须为对象的 UTF-8 JSON。"""
    if not path.is_file():
        _fail("missing_file", path.name, "", "必需文件不存在。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        _fail("invalid_encoding", path.name, "", "文件必须使用 UTF-8 编码。")
    except json.JSONDecodeError as exc:
        _fail("invalid_json", path.name, "", f"JSON 解析失败：{exc.msg}。")
    if not isinstance(payload, dict):
        _fail("invalid_json_type", path.name, "", "JSON 顶层必须是对象。")
    return payload


def _unique(items: Sequence[Any], field_name: str, file_name: str) -> None:
    """校验一组内部对象的业务主键唯一。"""
    seen: set[str] = set()
    for item in items:
        value = str(getattr(item, field_name))
        if value in seen:
            _fail("duplicate_key", file_name, field_name, f"存在重复编码 {value!r}。")
        seen.add(value)


def _load_sites(root: Path) -> Tuple[StorageCandidateSite, ...]:
    """加载并校验候选站点。"""
    file_name = CONTRACT_FILE_NAMES[0]
    rows = _read_csv(root / file_name, SITE_COLUMNS)
    items = []
    for row_number, row in enumerate(rows, start=2):
        prefix = f"row[{row_number}]"
        raw_codes = _text(row["allowed_technology_codes"], file_name, f"{prefix}.allowed_technology_codes").split("|")
        if any(not code.strip() for code in raw_codes):
            _fail("invalid_technology_list", file_name, f"{prefix}.allowed_technology_codes", "技术编码之间不能包含空项。")
        allowed_codes = tuple(code.strip() for code in raw_codes)
        if not allowed_codes or len(set(allowed_codes)) != len(allowed_codes):
            _fail("invalid_technology_list", file_name, f"{prefix}.allowed_technology_codes", "必须包含不重复的技术编码。")
        start = _number(row["storage_section_start_km"], file_name, f"{prefix}.storage_section_start_km", minimum=0.0)
        end = _number(row["storage_section_end_km"], file_name, f"{prefix}.storage_section_end_km", minimum=0.0)
        position = _number(row["position_km"], file_name, f"{prefix}.position_km", minimum=0.0)
        if end <= start:
            _fail("invalid_storage_section", file_name, f"{prefix}.storage_section_end_km", "服务区段终点必须大于起点。")
        if not start <= position <= end:
            _fail("site_outside_storage_section", file_name, f"{prefix}.position_km", "站点公里标必须位于服务区段内。")
        buildable = _boolean(row["buildable"], file_name, f"{prefix}.buildable")
        max_connection = float(_number(row["max_connection_power_kw"], file_name, f"{prefix}.max_connection_power_kw", minimum=0.0))
        max_capacity = float(_number(row["max_capacity_kwh"], file_name, f"{prefix}.max_capacity_kwh", minimum=0.0))
        if buildable and (max_connection <= 0.0 or max_capacity <= 0.0):
            _fail("buildable_site_without_capacity", file_name, prefix, "可建设站点的接入功率和容量上限必须大于 0。")
        items.append(StorageCandidateSite(
            site_code=_text(row["site_code"], file_name, f"{prefix}.site_code"),
            site_name=_text(row["site_name"], file_name, f"{prefix}.site_name"),
            position_km=float(position),
            power_arm_code=_text(row["power_arm_code"], file_name, f"{prefix}.power_arm_code"),
            storage_section_start_km=float(start),
            storage_section_end_km=float(end),
            direction=_enum(row["direction"], DIRECTIONS, file_name, f"{prefix}.direction"),
            buildable=buildable,
            max_connection_power_kw=max_connection,
            max_capacity_kwh=max_capacity,
            fixed_site_cost_cny=float(_number(row["fixed_site_cost_cny"], file_name, f"{prefix}.fixed_site_cost_cny", minimum=0.0)),
            allowed_technology_codes=allowed_codes,
            data_status=_enum(row["data_status"], DATA_STATUSES, file_name, f"{prefix}.data_status"),
            source_note=_text(row["source_note"], file_name, f"{prefix}.source_note", required=False),
        ))
    _unique(items, "site_code", file_name)
    return tuple(sorted(items, key=lambda item: item.site_code))


def _load_technologies(root: Path) -> Tuple[StorageTechnology, ...]:
    """加载并校验储能技术参数族。"""
    file_name = CONTRACT_FILE_NAMES[1]
    rows = _read_csv(root / file_name, TECHNOLOGY_COLUMNS)
    items = []
    for row_number, row in enumerate(rows, start=2):
        prefix = f"row[{row_number}]"
        field = lambda name: f"{prefix}.{name}"
        min_capacity = float(_number(row["min_capacity_kwh"], file_name, field("min_capacity_kwh"), minimum=0.0))
        max_capacity = float(_number(row["max_capacity_kwh"], file_name, field("max_capacity_kwh"), minimum=0.0))
        min_charge = float(_number(row["min_charge_power_kw"], file_name, field("min_charge_power_kw"), minimum=0.0))
        max_charge = float(_number(row["max_charge_power_kw"], file_name, field("max_charge_power_kw"), minimum=0.0))
        min_discharge = float(_number(row["min_discharge_power_kw"], file_name, field("min_discharge_power_kw"), minimum=0.0))
        max_discharge = float(_number(row["max_discharge_power_kw"], file_name, field("max_discharge_power_kw"), minimum=0.0))
        min_soc = float(_number(row["min_soc_ratio"], file_name, field("min_soc_ratio"), minimum=0.0, maximum=1.0))
        max_soc = float(_number(row["max_soc_ratio"], file_name, field("max_soc_ratio"), minimum=0.0, maximum=1.0))
        if max_capacity < min_capacity or max_charge < min_charge or max_discharge < min_discharge:
            _fail("invalid_min_max", file_name, prefix, "容量或功率上限不能小于下限。")
        if max_soc <= min_soc:
            _fail("invalid_soc_ratio", file_name, prefix, "最大 SOC 比例必须大于最小 SOC 比例。")
        items.append(StorageTechnology(
            technology_code=_text(row["technology_code"], file_name, field("technology_code")),
            technology_name=_text(row["technology_name"], file_name, field("technology_name")),
            min_capacity_kwh=min_capacity,
            max_capacity_kwh=max_capacity,
            capacity_step_kwh=_optional_positive_step(row["capacity_step_kwh"], file_name, field("capacity_step_kwh")),
            min_charge_power_kw=min_charge,
            max_charge_power_kw=max_charge,
            charge_power_step_kw=_optional_positive_step(row["charge_power_step_kw"], file_name, field("charge_power_step_kw")),
            min_discharge_power_kw=min_discharge,
            max_discharge_power_kw=max_discharge,
            discharge_power_step_kw=_optional_positive_step(row["discharge_power_step_kw"], file_name, field("discharge_power_step_kw")),
            charge_efficiency=float(_number(row["charge_efficiency"], file_name, field("charge_efficiency"), minimum=0.000001, maximum=1.0)),
            discharge_efficiency=float(_number(row["discharge_efficiency"], file_name, field("discharge_efficiency"), minimum=0.000001, maximum=1.0)),
            min_soc_ratio=min_soc,
            max_soc_ratio=max_soc,
            self_discharge_rate_per_hour=float(_number(row["self_discharge_rate_per_hour"], file_name, field("self_discharge_rate_per_hour"), minimum=0.0, maximum=1.0)),
            calendar_life_years=float(_number(row["calendar_life_years"], file_name, field("calendar_life_years"), minimum=0.000001)),
            cycle_life=float(_number(row["cycle_life"], file_name, field("cycle_life"), minimum=0.000001)),
            fixed_device_cost_cny=float(_number(row["fixed_device_cost_cny"], file_name, field("fixed_device_cost_cny"), minimum=0.0)),
            cost_per_kwh_cny=float(_number(row["cost_per_kwh_cny"], file_name, field("cost_per_kwh_cny"), minimum=0.0)),
            charge_power_cost_per_kw_cny=float(_number(row["charge_power_cost_per_kw_cny"], file_name, field("charge_power_cost_per_kw_cny"), minimum=0.0)),
            discharge_power_cost_per_kw_cny=float(_number(row["discharge_power_cost_per_kw_cny"], file_name, field("discharge_power_cost_per_kw_cny"), minimum=0.0)),
            annual_om_rate=float(_number(row["annual_om_rate"], file_name, field("annual_om_rate"), minimum=0.0, maximum=1.0)),
            throughput_degradation_cost_per_kwh=float(_number(row["throughput_degradation_cost_per_kwh"], file_name, field("throughput_degradation_cost_per_kwh"), minimum=0.0)),
            data_status=_enum(row["data_status"], DATA_STATUSES, file_name, field("data_status")),
            source_note=_text(row["source_note"], file_name, field("source_note"), required=False),
        ))
    _unique(items, "technology_code", file_name)
    return tuple(sorted(items, key=lambda item: item.technology_code))


def _load_options(root: Path) -> Tuple[StorageSiteTechnologyOption, ...]:
    """加载候选站点和技术关联。"""
    file_name = CONTRACT_FILE_NAMES[2]
    rows = _read_csv(root / file_name, OPTION_COLUMNS)
    items = []
    keys: set[Tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        prefix = f"row[{row_number}]"
        site_code = _text(row["site_code"], file_name, f"{prefix}.site_code")
        technology_code = _text(row["technology_code"], file_name, f"{prefix}.technology_code")
        key = (site_code, technology_code)
        if key in keys:
            _fail("duplicate_key", file_name, prefix, f"存在重复关联 {key!r}。")
        keys.add(key)
        min_capacity = _number(row["min_capacity_kwh"], file_name, f"{prefix}.min_capacity_kwh", minimum=0.0, optional=True)
        max_capacity = _number(row["max_capacity_kwh"], file_name, f"{prefix}.max_capacity_kwh", minimum=0.0, optional=True)
        if min_capacity is not None and max_capacity is not None and max_capacity < min_capacity:
            _fail("invalid_min_max", file_name, prefix, "站点容量上限不能小于下限。")
        items.append(StorageSiteTechnologyOption(
            site_code=site_code,
            technology_code=technology_code,
            min_capacity_kwh=min_capacity,
            max_capacity_kwh=max_capacity,
            max_charge_power_kw=_number(row["max_charge_power_kw"], file_name, f"{prefix}.max_charge_power_kw", minimum=0.0, optional=True),
            max_discharge_power_kw=_number(row["max_discharge_power_kw"], file_name, f"{prefix}.max_discharge_power_kw", minimum=0.0, optional=True),
            max_unit_count=int(_integer(row["max_unit_count"], file_name, f"{prefix}.max_unit_count", minimum=1)),
            available=_boolean(row["available"], file_name, f"{prefix}.available"),
            source_note=_text(row["source_note"], file_name, f"{prefix}.source_note", required=False),
        ))
    return tuple(sorted(items, key=lambda item: (item.site_code, item.technology_code)))


SCENARIO_ROOT_REQUIRED = {"schema_version", "scenario_set_code", "scenarios"}
SCENARIO_ITEM_REQUIRED = {
    "scenario_code", "scenario_name", "weight", "core_for_feasibility",
    "grid_price_per_kwh", "demand_charge_per_kw_year", "wasted_energy_penalty_per_kwh",
    "parameter_overrides", "data_status",
}
SCENARIO_ITEM_OPTIONAL = {
    "timetable_relative_path", "schedule_template", "storage_outage_site_codes", "source_note",
}
SCHEDULE_TEMPLATE_FIELDS = {
    "heavy_count", "empty_count", "heavy_headway_s", "empty_headway_s", "heavy_empty_phase_s",
}


def _load_scenarios(root: Path) -> Tuple[str, Tuple[StoragePlanningScenario, ...]]:
    """加载概率权重场景集，并校验运行图引用和合成运行模板互斥。"""
    file_name = CONTRACT_FILE_NAMES[3]
    payload = _read_json(root / file_name)
    _check_keys(payload, required=SCENARIO_ROOT_REQUIRED, optional=set(), file_name=file_name, field="root")
    if payload["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported_schema_version", file_name, "schema_version", f"只支持 {SCHEMA_VERSION}。")
    scenario_set_code = _text(payload["scenario_set_code"], file_name, "scenario_set_code")
    raw_items = payload["scenarios"]
    if not isinstance(raw_items, list) or not raw_items:
        _fail("invalid_scenarios", file_name, "scenarios", "必须是非空对象数组。")
    items = []
    for index, raw in enumerate(raw_items):
        prefix = f"scenarios[{index}]"
        if not isinstance(raw, dict):
            _fail("invalid_json_type", file_name, prefix, "必须是对象。")
        _check_keys(raw, required=SCENARIO_ITEM_REQUIRED, optional=SCENARIO_ITEM_OPTIONAL, file_name=file_name, field=prefix)
        timetable_raw = raw.get("timetable_relative_path")
        schedule_raw = raw.get("schedule_template")
        has_timetable = timetable_raw is not None and str(timetable_raw).strip() != ""
        has_schedule = schedule_raw is not None
        if has_timetable == has_schedule:
            _fail("scenario_schedule_source", file_name, prefix, "必须且只能提供 timetable_relative_path 或 schedule_template 之一。")
        timetable_path = _relative_reference(timetable_raw, file_name, f"{prefix}.timetable_relative_path") if has_timetable else None
        schedule_template: Optional[StoragePlanningScheduleTemplate] = None
        if has_schedule:
            if not isinstance(schedule_raw, dict):
                _fail("invalid_json_type", file_name, f"{prefix}.schedule_template", "必须是对象。")
            _check_keys(schedule_raw, required=SCHEDULE_TEMPLATE_FIELDS, optional=set(), file_name=file_name, field=f"{prefix}.schedule_template")
            schedule_template = StoragePlanningScheduleTemplate(
                heavy_count=int(_integer(schedule_raw["heavy_count"], file_name, f"{prefix}.schedule_template.heavy_count", minimum=0)),
                empty_count=int(_integer(schedule_raw["empty_count"], file_name, f"{prefix}.schedule_template.empty_count", minimum=0)),
                heavy_headway_s=int(_integer(schedule_raw["heavy_headway_s"], file_name, f"{prefix}.schedule_template.heavy_headway_s", minimum=1)),
                empty_headway_s=int(_integer(schedule_raw["empty_headway_s"], file_name, f"{prefix}.schedule_template.empty_headway_s", minimum=1)),
                heavy_empty_phase_s=int(_integer(schedule_raw["heavy_empty_phase_s"], file_name, f"{prefix}.schedule_template.heavy_empty_phase_s", minimum=0)),
            )
            if schedule_template.heavy_count + schedule_template.empty_count <= 0:
                _fail("empty_transport_scenario", file_name, f"{prefix}.schedule_template", "重车和空车数量不能同时为 0。")
        overrides = raw["parameter_overrides"]
        if not isinstance(overrides, dict):
            _fail("invalid_json_type", file_name, f"{prefix}.parameter_overrides", "必须是对象。")
        parsed_overrides: Dict[str, float] = {}
        for key, value in sorted(overrides.items()):
            parsed_key = _text(key, file_name, f"{prefix}.parameter_overrides.key")
            if parsed_key not in PARAMETER_OVERRIDE_FIELDS:
                _fail("unknown_parameter_override", file_name, f"{prefix}.parameter_overrides.{parsed_key}", f"允许值为 {sorted(PARAMETER_OVERRIDE_FIELDS)}。")
            parsed_overrides[parsed_key] = float(
                _number(value, file_name, f"{prefix}.parameter_overrides.{key}", minimum=0.0)
            )
        outage_raw = raw.get("storage_outage_site_codes", [])
        if not isinstance(outage_raw, list):
            _fail("invalid_json_type", file_name, f"{prefix}.storage_outage_site_codes", "必须是字符串数组。")
        outage_codes = tuple(sorted({_text(value, file_name, f"{prefix}.storage_outage_site_codes") for value in outage_raw}))
        items.append(StoragePlanningScenario(
            scenario_code=_text(raw["scenario_code"], file_name, f"{prefix}.scenario_code"),
            scenario_name=_text(raw["scenario_name"], file_name, f"{prefix}.scenario_name"),
            weight=float(_number(raw["weight"], file_name, f"{prefix}.weight", minimum=0.000000001, maximum=1.0)),
            core_for_feasibility=_boolean(raw["core_for_feasibility"], file_name, f"{prefix}.core_for_feasibility"),
            timetable_relative_path=timetable_path,
            schedule_template=schedule_template,
            grid_price_per_kwh=float(_number(raw["grid_price_per_kwh"], file_name, f"{prefix}.grid_price_per_kwh", minimum=0.0)),
            demand_charge_per_kw_year=float(_number(raw["demand_charge_per_kw_year"], file_name, f"{prefix}.demand_charge_per_kw_year", minimum=0.0)),
            wasted_energy_penalty_per_kwh=float(_number(raw["wasted_energy_penalty_per_kwh"], file_name, f"{prefix}.wasted_energy_penalty_per_kwh", minimum=0.0)),
            parameter_overrides=tuple(sorted(parsed_overrides.items())),
            storage_outage_site_codes=outage_codes,
            data_status=_enum(raw["data_status"], DATA_STATUSES, file_name, f"{prefix}.data_status"),
            source_note=_text(raw.get("source_note"), file_name, f"{prefix}.source_note", required=False),
        ))
    _unique(items, "scenario_code", file_name)
    if abs(sum(item.weight for item in items) - 1.0) > 1e-9:
        _fail("scenario_weight_sum", file_name, "scenarios.weight", "概率权重之和必须为 1。")
    if not any(item.core_for_feasibility for item in items):
        _fail("missing_core_scenario", file_name, "scenarios", "至少需要一个核心可行性场景。")
    for item in items:
        if item.timetable_relative_path is not None and not (root / item.timetable_relative_path).is_file():
            _fail("missing_timetable_reference", file_name, item.scenario_code, f"运行图文件不存在：{item.timetable_relative_path}。")
    return scenario_set_code, tuple(sorted(items, key=lambda item: item.scenario_code))


POLICY_REQUIRED = {
    "schema_version", "policy_code", "planning_horizon_years", "discount_rate",
    "analysis_days_per_year", "max_site_count", "total_budget_cny", "allow_no_build",
    "target_final_soc_rule", "final_soc_tolerance_kwh", "objective_mode",
    "include_demand_charge", "allow_timetable_coordination", "coordination_shortlist_size",
    "core_scenarios_must_all_be_feasible", "risk_measure", "cvar_alpha",
    "minimum_grid_reduction_kwh", "minimum_annual_saving_cny", "solver_profile",
    "max_wall_clock_s", "seed", "data_status",
}
POLICY_OPTIONAL = {"source_note"}


def _load_policy(root: Path) -> StoragePlanningPolicy:
    """加载规划业务策略和求解预算。"""
    file_name = CONTRACT_FILE_NAMES[4]
    raw = _read_json(root / file_name)
    _check_keys(raw, required=POLICY_REQUIRED, optional=POLICY_OPTIONAL, file_name=file_name, field="root")
    if raw["schema_version"] != SCHEMA_VERSION:
        _fail("unsupported_schema_version", file_name, "schema_version", f"只支持 {SCHEMA_VERSION}。")
    risk_measure = _enum(raw["risk_measure"], RISK_MEASURES, file_name, "risk_measure")
    cvar_alpha = _number(raw["cvar_alpha"], file_name, "cvar_alpha", minimum=0.0, maximum=1.0, optional=True)
    if risk_measure == "cvar" and (cvar_alpha is None or not 0.0 < cvar_alpha < 1.0):
        _fail("invalid_cvar_alpha", file_name, "cvar_alpha", "CVaR 模式必须提供 0 到 1 之间的 alpha。")
    if risk_measure != "cvar" and cvar_alpha is not None:
        _fail("unexpected_cvar_alpha", file_name, "cvar_alpha", "非 CVaR 模式必须将 cvar_alpha 设为 null。")
    return StoragePlanningPolicy(
        policy_code=_text(raw["policy_code"], file_name, "policy_code"),
        planning_horizon_years=int(_integer(raw["planning_horizon_years"], file_name, "planning_horizon_years", minimum=1)),
        discount_rate=float(_number(raw["discount_rate"], file_name, "discount_rate", minimum=0.0, maximum=1.0)),
        analysis_days_per_year=int(_integer(raw["analysis_days_per_year"], file_name, "analysis_days_per_year", minimum=1)),
        max_site_count=int(_integer(raw["max_site_count"], file_name, "max_site_count", minimum=0)),
        total_budget_cny=float(_number(raw["total_budget_cny"], file_name, "total_budget_cny", minimum=0.0)),
        allow_no_build=_boolean(raw["allow_no_build"], file_name, "allow_no_build"),
        target_final_soc_rule=_enum(raw["target_final_soc_rule"], TARGET_FINAL_SOC_RULES, file_name, "target_final_soc_rule"),
        final_soc_tolerance_kwh=float(_number(raw["final_soc_tolerance_kwh"], file_name, "final_soc_tolerance_kwh", minimum=0.0)),
        objective_mode=_enum(raw["objective_mode"], OBJECTIVE_MODES, file_name, "objective_mode"),
        include_demand_charge=_boolean(raw["include_demand_charge"], file_name, "include_demand_charge"),
        allow_timetable_coordination=_boolean(raw["allow_timetable_coordination"], file_name, "allow_timetable_coordination"),
        coordination_shortlist_size=int(_integer(raw["coordination_shortlist_size"], file_name, "coordination_shortlist_size", minimum=0)),
        core_scenarios_must_all_be_feasible=_boolean(raw["core_scenarios_must_all_be_feasible"], file_name, "core_scenarios_must_all_be_feasible"),
        risk_measure=risk_measure,
        cvar_alpha=cvar_alpha,
        minimum_grid_reduction_kwh=float(_number(raw["minimum_grid_reduction_kwh"], file_name, "minimum_grid_reduction_kwh", minimum=0.0)),
        minimum_annual_saving_cny=float(_number(raw["minimum_annual_saving_cny"], file_name, "minimum_annual_saving_cny", minimum=0.0)),
        solver_profile=_enum(raw["solver_profile"], SOLVER_PROFILES, file_name, "solver_profile"),
        max_wall_clock_s=int(_integer(raw["max_wall_clock_s"], file_name, "max_wall_clock_s", minimum=1)),
        seed=int(_integer(raw["seed"], file_name, "seed", minimum=0)),
        data_status=_enum(raw["data_status"], DATA_STATUSES, file_name, "data_status"),
        source_note=_text(raw.get("source_note"), file_name, "source_note", required=False),
    )


def _validate_site_allowed_technologies(
    sites: Sequence[StorageCandidateSite],
    technology_by_code: Mapping[str, StorageTechnology],
    available_pairs: set[Tuple[str, str]],
) -> None:
    """校验站点允许技术列表及可建设站点的有效选项覆盖。"""
    for site in sites:
        unknown = sorted(set(site.allowed_technology_codes) - set(technology_by_code))
        if unknown:
            _fail("unknown_technology_reference", CONTRACT_FILE_NAMES[0], site.site_code, f"引用了未知技术：{unknown}。")
        if site.buildable and not any((site.site_code, code) in available_pairs for code in site.allowed_technology_codes):
            _fail("buildable_site_without_option", CONTRACT_FILE_NAMES[2], site.site_code, "可建设站点至少需要一个可用技术关联。")


def _validate_option_reference_and_domain(
    option: StorageSiteTechnologyOption,
    site_by_code: Mapping[str, StorageCandidateSite],
    technology_by_code: Mapping[str, StorageTechnology],
) -> None:
    """校验一个站点—技术关系的引用、容量交集和接入功率。"""
    if option.site_code not in site_by_code:
        _fail("unknown_site_reference", CONTRACT_FILE_NAMES[2], option.site_code, "引用了未知候选站点。")
    if option.technology_code not in technology_by_code:
        _fail("unknown_technology_reference", CONTRACT_FILE_NAMES[2], option.technology_code, "引用了未知储能技术。")
    site = site_by_code[option.site_code]
    technology = technology_by_code[option.technology_code]
    if option.technology_code not in site.allowed_technology_codes:
        _fail("technology_not_allowed_at_site", CONTRACT_FILE_NAMES[2], option.site_code, "关联技术不在站点允许列表中。")
    effective_max_capacity = min(
        site.max_capacity_kwh,
        technology.max_capacity_kwh,
        option.max_capacity_kwh if option.max_capacity_kwh is not None else math.inf,
    )
    effective_min_capacity = max(
        technology.min_capacity_kwh,
        option.min_capacity_kwh if option.min_capacity_kwh is not None else 0.0,
    )
    if option.available and effective_max_capacity < effective_min_capacity:
        _fail("empty_capacity_domain", CONTRACT_FILE_NAMES[2], option.site_code, "站点与技术容量边界交集为空。")
    if option.max_charge_power_kw is not None and option.max_charge_power_kw > site.max_connection_power_kw:
        _fail("site_power_limit_exceeded", CONTRACT_FILE_NAMES[2], option.site_code, "站点技术充电功率上限超过接入上限。")
    if option.max_discharge_power_kw is not None and option.max_discharge_power_kw > site.max_connection_power_kw:
        _fail("site_power_limit_exceeded", CONTRACT_FILE_NAMES[2], option.site_code, "站点技术放电功率上限超过接入上限。")
    effective_max_charge = min(
        site.max_connection_power_kw,
        technology.max_charge_power_kw,
        option.max_charge_power_kw if option.max_charge_power_kw is not None else math.inf,
    )
    effective_max_discharge = min(
        site.max_connection_power_kw,
        technology.max_discharge_power_kw,
        option.max_discharge_power_kw if option.max_discharge_power_kw is not None else math.inf,
    )
    if option.available and effective_max_charge < technology.min_charge_power_kw:
        _fail("empty_power_domain", CONTRACT_FILE_NAMES[2], option.site_code, "站点与技术充电功率边界交集为空。")
    if option.available and effective_max_discharge < technology.min_discharge_power_kw:
        _fail("empty_power_domain", CONTRACT_FILE_NAMES[2], option.site_code, "站点与技术放电功率边界交集为空。")


def _validate_policy_cross_rules(
    sites: Sequence[StorageCandidateSite],
    policy: StoragePlanningPolicy,
) -> None:
    """校验依赖候选站点数量或其他策略字段的组合规则。"""
    if policy.max_site_count > sum(1 for item in sites if item.buildable):
        _fail("max_site_count_exceeds_candidates", CONTRACT_FILE_NAMES[4], "max_site_count", "最大建设数量不能超过可建设候选站点数。")
    if not policy.allow_no_build and policy.max_site_count == 0:
        _fail("impossible_build_policy", CONTRACT_FILE_NAMES[4], "allow_no_build", "禁止不建设时，最大站点数必须大于 0。")
    if policy.allow_timetable_coordination and policy.coordination_shortlist_size <= 0:
        _fail("invalid_coordination_shortlist", CONTRACT_FILE_NAMES[4], "coordination_shortlist_size", "启用运行图协同时，入围数量必须大于 0。")
    if not policy.allow_timetable_coordination and policy.coordination_shortlist_size != 0:
        _fail("unexpected_coordination_shortlist", CONTRACT_FILE_NAMES[4], "coordination_shortlist_size", "未启用运行图协同时，入围数量必须为 0。")


def _validate_cross_references(
    sites: Sequence[StorageCandidateSite],
    technologies: Sequence[StorageTechnology],
    options: Sequence[StorageSiteTechnologyOption],
    scenarios: Sequence[StoragePlanningScenario],
    policy: StoragePlanningPolicy,
) -> None:
    """编排跨文件引用、容量域和策略组合校验。"""
    site_by_code = {item.site_code: item for item in sites}
    technology_by_code = {item.technology_code: item for item in technologies}
    available_pairs = {(item.site_code, item.technology_code) for item in options if item.available}
    _validate_site_allowed_technologies(sites, technology_by_code, available_pairs)
    for option in options:
        _validate_option_reference_and_domain(option, site_by_code, technology_by_code)
    for scenario in scenarios:
        unknown_outages = sorted(set(scenario.storage_outage_site_codes) - set(site_by_code))
        if unknown_outages:
            _fail(
                "unknown_storage_outage_site",
                CONTRACT_FILE_NAMES[3],
                scenario.scenario_code,
                f"停运设备引用未知候选站点：{unknown_outages}。",
            )
    _validate_policy_cross_rules(sites, policy)


def _canonical_payload(
    scenario_set_code: str,
    sites: Sequence[StorageCandidateSite],
    technologies: Sequence[StorageTechnology],
    options: Sequence[StorageSiteTechnologyOption],
    scenarios: Sequence[StoragePlanningScenario],
    policy: StoragePlanningPolicy,
) -> Dict[str, Any]:
    """生成不含本地路径、按业务主键排序的语义载荷。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_set_code": scenario_set_code,
        "sites": [asdict(item) for item in sorted(sites, key=lambda item: item.site_code)],
        "technologies": [asdict(item) for item in sorted(technologies, key=lambda item: item.technology_code)],
        "site_technology_options": [
            asdict(item) for item in sorted(options, key=lambda item: (item.site_code, item.technology_code))
        ],
        "scenarios": [asdict(item) for item in sorted(scenarios, key=lambda item: item.scenario_code)],
        "policy": asdict(policy),
    }


def storage_planning_input_fingerprint(payload: Mapping[str, Any]) -> str:
    """计算规范化规划输入的稳定 SHA-256。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _recommendation_level(statuses: Iterable[str]) -> str:
    """按最弱关键输入状态给出结果可使用等级。"""
    status_set = set(statuses)
    if "synthetic" in status_set:
        return "diagnostic_only"
    if "planning_placeholder" in status_set:
        return "planning_sensitivity"
    if status_set <= {"official", "derived_from_official"}:
        return "engineering_candidate"
    return "planning_sensitivity"


def _normalized_power_arm_direction(value: Any, file_name: str, field: str) -> str:
    """将既有供电臂中英文方向统一为规划合同方向。"""
    raw = _text(value, file_name, field, required=False).lower()
    aliases = {
        "forward": "forward",
        "down": "forward",
        "下行": "forward",
        "reverse": "reverse",
        "up": "reverse",
        "上行": "reverse",
        "both": "both",
        "双向": "both",
        "single": "both",
        "单线": "both",
        "": "both",
    }
    if raw not in aliases:
        _fail("unknown_power_arm_direction", file_name, field, f"无法识别供电臂方向 {value!r}。")
    return aliases[raw]


def validate_storage_planning_power_arm_references(
    bundle: StoragePlanningBundle,
    power_arm_path: Path | str,
) -> None:
    """用指定数据版本的供电臂表核验候选站点代码、公里范围和方向。"""
    path = Path(power_arm_path)
    if not path.is_file():
        _fail("missing_power_arm_file", str(path), "", "供电臂交叉核验文件不存在。")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            required = {"start_km", "end_km", "direction"}
            if not required <= columns or not ({"power_arm_id", "section_id"} & columns):
                _fail("invalid_power_arm_header", path.name, "header", "缺少供电臂编码、起终点或方向字段。")
            rows = list(reader)
    except UnicodeDecodeError:
        _fail("invalid_encoding", path.name, "", "供电臂文件必须使用 UTF-8 编码。")
    intervals: Dict[str, list[Tuple[float, float, str]]] = {}
    for row_number, row in enumerate(rows, start=2):
        codes = {
            str(row.get(name) or "").strip()
            for name in ("power_arm_id", "section_id")
            if str(row.get(name) or "").strip()
        }
        start = float(_number(row.get("start_km"), path.name, f"row[{row_number}].start_km", minimum=0.0))
        end = float(_number(row.get("end_km"), path.name, f"row[{row_number}].end_km", minimum=0.0))
        if end <= start:
            _fail("invalid_power_arm_interval", path.name, f"row[{row_number}]", "供电臂终点必须大于起点。")
        direction = _normalized_power_arm_direction(row.get("direction"), path.name, f"row[{row_number}].direction")
        for code in codes:
            intervals.setdefault(code, []).append((start, end, direction))
    for site in bundle.sites:
        candidates = intervals.get(site.power_arm_code, [])
        if not candidates:
            _fail("unknown_power_arm_reference", CONTRACT_FILE_NAMES[0], site.site_code, f"供电臂 {site.power_arm_code!r} 不存在。")
        matching = [
            item for item in candidates
            if item[0] <= site.position_km <= item[1]
            and site.storage_section_start_km < item[1]
            and site.storage_section_end_km > item[0]
            and (site.direction == "both" or item[2] == "both" or site.direction == item[2])
        ]
        if not matching:
            _fail("site_power_arm_mismatch", CONTRACT_FILE_NAMES[0], site.site_code, "站点公里标、服务区段或方向与引用供电臂不一致。")


def load_storage_planning_bundle(source_dir: Path | str) -> StoragePlanningBundle:
    """加载完整阶段A文件集，任何合同错误都会阻断并给出明确位置。"""
    root = Path(source_dir).resolve()
    if not root.is_dir():
        _fail("missing_directory", str(root), "", "规划输入目录不存在。")
    sites = _load_sites(root)
    technologies = _load_technologies(root)
    options = _load_options(root)
    scenario_set_code, scenarios = _load_scenarios(root)
    policy = _load_policy(root)
    _validate_cross_references(sites, technologies, options, scenarios, policy)
    statuses = [item.data_status for item in sites]
    statuses += [item.data_status for item in technologies]
    statuses += [item.data_status for item in scenarios]
    statuses.append(policy.data_status)
    payload = _canonical_payload(scenario_set_code, sites, technologies, options, scenarios, policy)
    fingerprint = storage_planning_input_fingerprint(payload)
    return StoragePlanningBundle(
        source_dir=root,
        scenario_set_code=scenario_set_code,
        sites=sites,
        technologies=technologies,
        site_technology_options=options,
        scenarios=scenarios,
        policy=policy,
        input_fingerprint_sha256=fingerprint,
        recommendation_level=_recommendation_level(statuses),
    )


def validate_storage_planning_inputs(
    source_dir: Path | str,
    power_arm_path: Path | str | None = None,
) -> Dict[str, Any]:
    """执行非抛出式校验，便于命令行和平台生成质量报告。"""
    try:
        bundle = load_storage_planning_bundle(source_dir)
        if power_arm_path is not None:
            validate_storage_planning_power_arm_references(bundle, power_arm_path)
    except StoragePlanningContractError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": False,
            "source_dir": str(Path(source_dir).resolve()),
            "error_count": 1,
            "issues": [exc.to_dict()],
        }
    summary = bundle.summary()
    summary.update({
        "power_arm_reference_check_applied": power_arm_path is not None,
        "power_arm_path": None if power_arm_path is None else str(Path(power_arm_path).resolve()),
        "error_count": 0,
        "issues": [],
    })
    return summary


def write_storage_planning_validation_report(
    source_dir: Path | str,
    output_dir: Path | str,
    power_arm_path: Path | str | None = None,
) -> Dict[str, Any]:
    """校验阶段A输入并写出 JSON 摘要和 CSV 问题表。"""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    summary = validate_storage_planning_inputs(source_dir, power_arm_path)
    summary_path = output_root / "storage_planning_validation_summary.json"
    issues_path = output_root / "storage_planning_validation_issues.csv"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = ("severity", "code", "file", "field", "message")
    with issues_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summary.get("issues", []))
    return {
        **summary,
        "summary_path": str(summary_path),
        "issues_path": str(issues_path),
    }


def storage_planning_input_status_codes(bundle: "StoragePlanningBundle") -> List[str]:
    """汇总关键输入的数据状态标记，供结果解释与下游页面区分校核口径。"""
    codes = {item.data_status for item in bundle.sites}
    codes |= {item.data_status for item in bundle.technologies}
    codes |= {item.data_status for item in bundle.scenarios}
    codes.add(bundle.policy.data_status)
    return sorted(str(code) for code in codes if str(code).strip())
