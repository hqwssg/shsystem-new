"""实测传感数据的只读归一化、质量审计与回放接口。

该模块只处理输入边界，不改变控制器参数或物理模型。原始文件永远只读；
累计电表读数只在相邻有效样本之间计算差值，回退/复位不会被静默当成负能量。
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from regenerative_braking.dynamics.train_braking_model import BrakingInput

if TYPE_CHECKING:
    from regenerative_braking.simulation.profiles import ProfileSeries


class MeasuredDataError(ValueError):
    """实测数据无法安全归一化时抛出的错误。"""


@dataclass(frozen=True)
class MeasuredRunManifest:
    """运行元数据清单；用于锁定时钟、单位和计量口径。"""

    run_id: str
    time_basis: str
    sampling_period_s: float | None
    timezone: str
    meter_point: str
    meter_direction: str
    meter_multiplier: float
    source_status: str = "unknown"


def read_run_manifest(path: str | Path) -> MeasuredRunManifest:
    source = Path(path).resolve()
    if not source.is_file():
        raise MeasuredDataError(f"运行元数据清单不存在：{source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MeasuredDataError(f"运行元数据清单无法读取：{source}") from exc
    if not isinstance(payload, dict):
        raise MeasuredDataError("运行元数据清单必须是 JSON object")
    required = ("run_id", "time_basis", "timezone", "meter_point", "meter_direction")
    missing = [name for name in required if not str(payload.get(name, "")).strip()]
    if missing:
        raise MeasuredDataError(f"运行元数据清单缺少字段：{', '.join(missing)}")
    multiplier = payload.get("meter_multiplier", 1.0)
    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError) as exc:
        raise MeasuredDataError("meter_multiplier 必须为正数") from exc
    if not math.isfinite(multiplier) or multiplier <= 0.0:
        raise MeasuredDataError("meter_multiplier 必须为正有限数值")
    period = payload.get("sampling_period_s")
    if period is not None:
        try:
            period = float(period)
        except (TypeError, ValueError) as exc:
            raise MeasuredDataError("sampling_period_s 必须为正数") from exc
        if not math.isfinite(period) or period <= 0.0:
            raise MeasuredDataError("sampling_period_s 必须为正有限数值")
    return MeasuredRunManifest(
        run_id=str(payload["run_id"]),
        time_basis=str(payload["time_basis"]),
        sampling_period_s=period,
        timezone=str(payload["timezone"]),
        meter_point=str(payload["meter_point"]),
        meter_direction=str(payload["meter_direction"]),
        meter_multiplier=multiplier,
        source_status=str(payload.get("source_status", "unknown")),
    )


@dataclass(frozen=True)
class MeasuredSample:
    time_s: float
    position_km: float | None = None
    speed_mps: float | None = None
    acceleration_mps2: float | None = None
    gradient_per_mille: float | None = None
    inclination_rad: float | None = None
    meter_cumulative_kwh: float | None = None
    meter_delta_kwh: float | None = None
    meter_power_w: float | None = None
    dc_voltage_v: float | None = None
    dc_current_a: float | None = None
    soc: float | None = None
    brake_command: float | None = None
    quality_flags: tuple[str, ...] = ()
    source_row: int = 0
    latitude_deg: float | None = None
    longitude_deg: float | None = None


@dataclass(frozen=True)
class MeasuredRun:
    run_id: str
    samples: tuple[MeasuredSample, ...]
    source_path: Path
    source_sha256: str
    source_status: str = "unknown"
    metadata: Mapping[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


_ALIASES: dict[str, tuple[str, ...]] = {
    "time_s": ("time_s", "timestamp_s", "timestamp", "时间_s", "时间戳_s"),
    "position_km": ("position_km", "position_m", "coordinate_km", "coordinate_m", "位置_km", "位置_m"),
    "latitude_deg": ("latitude_deg", "latitude", "lat", "纬度"),
    "longitude_deg": ("longitude_deg", "longitude", "lon", "lng", "经度"),
    "speed_mps": ("speed_mps", "speed_kmh", "velocity_mps", "velocity_kmh", "速度_mps", "速度_kmh"),
    "acceleration_mps2": ("acceleration_mps2", "accel_mps2", "acceleration", "加速度_mps2"),
    "gradient_per_mille": ("gradient_per_mille", "grade_per_mille", "坡度_千分比"),
    "inclination_rad": ("inclination_rad", "倾角_rad", "slope_angle_rad"),
    "meter_cumulative_kwh": ("meter_cumulative_kwh", "meter_kwh", "meter_reading_kwh", "车载电表_kwh"),
    "meter_power_w": ("meter_power_w", "meter_power_kw", "meter_kw", "电表功率_kw"),
    "dc_voltage_v": ("dc_voltage_v", "母线电压_v"),
    "dc_current_a": ("dc_current_a", "母线电流_a"),
    "soc": ("soc", "储能_soc"),
    "brake_command": ("brake_command", "brake_level", "制动指令"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: object, *, row: int, field: str, unit_scale: float = 1.0) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(str(value).strip()) * unit_scale
    except ValueError as exc:
        raise MeasuredDataError(f"第 {row} 行字段 {field} 不是数字：{value!r}") from exc
    if not math.isfinite(number):
        raise MeasuredDataError(f"第 {row} 行字段 {field} 不是有限值：{value!r}")
    return number


def _column(headers: Sequence[str], field: str) -> str | None:
    normalized = {header.strip().lower(): header for header in headers}
    for alias in _ALIASES[field]:
        if alias.lower() in normalized:
            return normalized[alias.lower()]
    return None


def _meter_deltas(samples: Sequence[MeasuredSample]) -> tuple[MeasuredSample, ...]:
    previous: float | None = None
    output: list[MeasuredSample] = []
    for sample in samples:
        flags = list(sample.quality_flags)
        delta: float | None = None
        current = sample.meter_cumulative_kwh
        if current is not None and previous is not None:
            if current + 1e-12 < previous:
                flags.append("meter_reset_or_rollback")
            else:
                delta = current - previous
        if current is not None:
            previous = current
        output.append(MeasuredSample(**{**sample.__dict__, "meter_delta_kwh": delta, "quality_flags": tuple(flags)}))
    return tuple(output)


def read_measured_csv(path: str | Path, *, run_id: str | None = None, source_status: str = "unknown") -> MeasuredRun:
    """只读读取 CSV，并将常见单位转换为 SI。"""
    source = Path(path).resolve()
    if not source.is_file():
        raise MeasuredDataError(f"实测数据文件不存在：{source}")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        time_column = _column(headers, "time_s")
        if time_column is None:
            raise MeasuredDataError("实测数据必须包含 time_s/timestamp_s/时间_s 字段")
        columns = {field: _column(headers, field) for field in _ALIASES}
        samples: list[MeasuredSample] = []
        previous_time: float | None = None
        for row_number, row in enumerate(reader, start=2):
            time_s = _number(row.get(time_column), row=row_number, field="time_s")
            assert time_s is not None
            flags: list[str] = []
            if previous_time is not None and time_s <= previous_time:
                flags.append("duplicate_or_backward_time")
            previous_time = time_s
            position = _number(row.get(columns["position_km"]), row=row_number, field="position") if columns["position_km"] else None
            if columns["position_km"] and columns["position_km"].lower().endswith("_m"):
                position = None if position is None else position / 1000.0
            speed = _number(row.get(columns["speed_mps"]), row=row_number, field="speed") if columns["speed_mps"] else None
            if columns["speed_mps"] and columns["speed_mps"].lower().endswith("_kmh"):
                speed = None if speed is None else speed / 3.6
            acceleration = _number(row.get(columns["acceleration_mps2"]), row=row_number, field="acceleration") if columns["acceleration_mps2"] else None
            gradient = _number(row.get(columns["gradient_per_mille"]), row=row_number, field="gradient") if columns["gradient_per_mille"] else None
            inclination = _number(row.get(columns["inclination_rad"]), row=row_number, field="inclination") if columns["inclination_rad"] else None
            cumulative = _number(row.get(columns["meter_cumulative_kwh"]), row=row_number, field="meter_cumulative_kwh") if columns["meter_cumulative_kwh"] else None
            power = _number(row.get(columns["meter_power_w"]), row=row_number, field="meter_power_w") if columns["meter_power_w"] else None
            if columns["meter_power_w"] and columns["meter_power_w"].lower().endswith("_kw"):
                power = None if power is None else power * 1000.0
            dc_voltage = _number(row.get(columns["dc_voltage_v"]), row=row_number, field="dc_voltage_v") if columns["dc_voltage_v"] else None
            dc_current = _number(row.get(columns["dc_current_a"]), row=row_number, field="dc_current_a") if columns["dc_current_a"] else None
            soc = _number(row.get(columns["soc"]), row=row_number, field="soc") if columns["soc"] else None
            brake = _number(row.get(columns["brake_command"]), row=row_number, field="brake_command") if columns["brake_command"] else None
            latitude = _number(row.get(columns["latitude_deg"]), row=row_number, field="latitude_deg") if columns["latitude_deg"] else None
            longitude = _number(row.get(columns["longitude_deg"]), row=row_number, field="longitude_deg") if columns["longitude_deg"] else None
            samples.append(MeasuredSample(time_s, position, speed, acceleration, gradient, inclination, cumulative, None, power, dc_voltage, dc_current, soc, brake, tuple(flags), row_number, latitude, longitude))
    return MeasuredRun(run_id or source.stem, _meter_deltas(samples), source, _sha256(source), source_status)


def audit_measured_run(
    run: MeasuredRun,
    *,
    max_gap_s: float = 1.0,
    position_speed_tolerance_mps: float = 5.0,
) -> dict[str, object]:
    samples = run.samples
    gaps: list[dict[str, float]] = []
    position_speed_residuals: list[float] = []
    for left, right in zip(samples, samples[1:]):  # noqa: RUF007 - 兼容 Python 3.9
        delta = right.time_s - left.time_s
        if delta > max_gap_s:
            gaps.append({"from_s": left.time_s, "to_s": right.time_s, "gap_s": delta})
        if delta > 0 and left.position_km is not None and right.position_km is not None and left.speed_mps is not None and right.speed_mps is not None:
            derived_speed = (right.position_km - left.position_km) * 1000.0 / delta
            position_speed_residuals.append(abs(derived_speed - (left.speed_mps + right.speed_mps) / 2.0))
    issues: list[str] = []
    if not samples:
        issues.append("empty_run")
    for sample in samples:
        issues.extend(sample.quality_flags)
        if sample.speed_mps is not None and sample.speed_mps < 0:
            issues.append("negative_speed")
        if sample.soc is not None and not 0.0 <= sample.soc <= 1.0:
            issues.append("soc_out_of_range")
        if sample.meter_cumulative_kwh is not None and sample.meter_cumulative_kwh < 0:
            issues.append("negative_meter_reading")
    if gaps:
        issues.append("sample_gap")
    max_position_speed_residual = max(position_speed_residuals, default=None)
    if max_position_speed_residual is not None and max_position_speed_residual > position_speed_tolerance_mps:
        issues.append("position_speed_inconsistent")
    fields = (
        "position_km",
        "latitude_deg",
        "longitude_deg",
        "speed_mps",
        "acceleration_mps2",
        "gradient_per_mille",
        "inclination_rad",
        "meter_cumulative_kwh",
        "dc_voltage_v",
        "dc_current_a",
        "soc",
        "brake_command",
    )
    coverage = {
        field: sum(getattr(sample, field) is not None for sample in samples) / len(samples) if samples else 0.0
        for field in fields
    }
    replay_blockers = [field for field in ("position_km", "speed_mps", "acceleration_mps2") if coverage[field] < 1.0]
    unique_issues = sorted(set(issues))
    return {
        "run_id": run.run_id,
        "source_path": str(run.source_path),
        "source_sha256": run.source_sha256,
        "source_status": run.source_status,
        "sample_count": len(samples),
        "duration_s": 0.0 if len(samples) < 2 else samples[-1].time_s - samples[0].time_s,
        "field_coverage": coverage,
        "replay_ready": not replay_blockers and not unique_issues,
        "replay_blockers": replay_blockers,
        "max_position_speed_residual_mps": max_position_speed_residual,
        "issues": unique_issues,
        "gaps": gaps,
        "status": "passed" if not unique_issues else "failed",
    }


def to_profile_series(run: MeasuredRun, *, scenario_id: str | None = None, dt: float | None = None) -> ProfileSeries:
    """把具备运动字段的实测行转换为回放输入；缺少制动指令时明确标记为假设。"""
    from regenerative_braking.simulation.profiles import ProfileSeries

    if not run.samples:
        raise MeasuredDataError("空实测序列不能转换为 ProfileSeries")
    converted: list[BrakingInput] = []
    assumed_brake = False
    for sample in run.samples:
        if sample.position_km is None or sample.speed_mps is None or sample.acceleration_mps2 is None:
            raise MeasuredDataError("回放需要 position、speed、acceleration 三类字段")
        gradient = sample.gradient_per_mille
        if gradient is None and sample.inclination_rad is not None:
            gradient = math.tan(sample.inclination_rad) * 1000.0
        if gradient is None:
            gradient = 0.0
        brake = sample.brake_command
        if brake is None:
            brake = 1.0
            assumed_brake = True
        converted.append(BrakingInput(sample.time_s, sample.position_km, sample.speed_mps, sample.acceleration_mps2, gradient, brake_command=brake))
    sample_dt = dt if dt is not None else (run.samples[1].time_s - run.samples[0].time_s if len(run.samples) > 1 else 0.0)
    if sample_dt <= 0.0:
        raise MeasuredDataError("回放需要正的采样周期 dt")
    notes = ("制动指令未由实测数据提供，已使用 brake_command=1 表示实际加速度回放。",) if assumed_brake else ()
    return ProfileSeries(scenario_id or f"measured_{run.run_id}", tuple(converted), sample_dt, "实测传感数据回放输入", notes)


def write_normalized_csv(run: MeasuredRun, path: str | Path) -> None:
    """写出归一化副本；不覆盖原始文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ["time_s", "position_km", "latitude_deg", "longitude_deg", "speed_mps", "acceleration_mps2", "gradient_per_mille", "inclination_rad", "meter_cumulative_kwh", "meter_delta_kwh", "meter_power_w", "dc_voltage_v", "dc_current_a", "soc", "brake_command", "quality_flags", "source_row"]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in run.samples:
            row = {field: getattr(sample, field) for field in fields if field != "quality_flags"}
            row["quality_flags"] = ";".join(sample.quality_flags)
            writer.writerow(row)


def write_audit_json(run: MeasuredRun, path: str | Path, *, max_gap_s: float = 1.0) -> dict[str, object]:
    report = audit_measured_run(run, max_gap_s=max_gap_s)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
