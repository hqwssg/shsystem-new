"""历史扰动回放输入合同、严格校验和算法观测转换。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json
import math

from energy_settlement import StorageDeviceRuntimeState, normalize_storage_runtime_states
from power_arm_electrical_limits import DynamicPowerArmLimit
from resource_constraints import ResourceUnavailability
from rolling_optimizer import DynamicTrainAddition, RollingCycleObservation
from operating_conditions import normalize_speed_restriction_direction


SCHEMA_VERSION = "1.3"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", SCHEMA_VERSION}
DATA_STATUS_VALUES = {"official", "derived_from_official", "planning_placeholder", "synthetic"}
EVENT_TYPES = {
    "train_delay",
    "train_cancelled",
    "train_added",
    "temporary_speed_restriction",
    "resource_unavailable",
    "power_arm_limit",
    "storage_device_state",
}


def _whole_seconds(value: Any, field_name: str) -> int:
    """读取非负整数秒，拒绝布尔值、小数和隐式截断。"""

    if isinstance(value, bool):
        raise ValueError(f"{field_name}必须是非负整数秒。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是非负整数秒。") from exc
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"{field_name}必须是非负整数秒。")
    return int(number)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name}不能为空。")
    return text


def _finite_number(value: Any, field_name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}必须是有限数值。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是有限数值。") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValueError(f"{field_name}必须是不小于{minimum}的有限数值。")
    return number


def _zoned_timestamp(value: Any, field_name: str) -> tuple[str, datetime]:
    """校验ISO 8601时间戳，并要求显式时区。"""

    text = _required_text(value, field_name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name}必须是ISO 8601时间戳。") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name}必须包含时区。")
    return text, parsed


def _train_id(value: Any, field_name: str) -> str:
    train_id = _required_text(value, field_name).upper()
    if (
        len(train_id) != 4
        or train_id[0] not in {"H", "E"}
        or not train_id[1:].isdigit()
        or int(train_id[1:]) <= 0
    ):
        raise ValueError(f"{field_name}必须使用H001或E001格式。")
    return train_id


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"{field_name}包含未批准字段：{sorted(unknown)}")


@dataclass(frozen=True)
class HistoricalDisturbanceEvent:
    """统一历史事件；缺少正式业务语义的类型会被标记为阻断。"""

    event_id: str
    event_type: str
    entity_id: str
    payload: Mapping[str, Any]
    applicable: bool
    blocking_reason: str = ""


@dataclass(frozen=True)
class HistoricalDisturbanceCycle:
    """一个回放周期的已确认现场状态快照。"""

    cycle_index: int
    current_time_s: int
    observed_heavy_delay_s: int
    observed_empty_delay_s: int
    source_record_ids: tuple[str, ...]
    observed_at: str = ""
    storage_device_states: tuple[StorageDeviceRuntimeState, ...] = ()
    storage_states_provided: bool = False
    events: tuple[HistoricalDisturbanceEvent, ...] = ()

    def to_observation(self) -> RollingCycleObservation:
        cancelled = tuple(
            event.entity_id for event in self.events
            if event.event_type == "train_cancelled" and event.applicable
        )
        additions = tuple(
            DynamicTrainAddition(
                event.entity_id,
                str(event.payload["train_type"]),
                int(event.payload["departure_s"]),
            )
            for event in self.events
            if event.event_type == "train_added" and event.applicable
        )
        outages = tuple(
            ResourceUnavailability(
                event.event_id,
                event.entity_id,
                str(event.payload["resource_type"]),
                int(event.payload["start_time_s"]),
                int(event.payload["end_time_s"]),
                str(event.payload.get("reason") or ""),
            )
            for event in self.events
            if event.event_type == "resource_unavailable" and event.applicable
        )
        power_limits = tuple(
            DynamicPowerArmLimit(
                event_id=event.event_id,
                power_arm_id=event.entity_id,
                start_time_s=int(event.payload["start_time_s"]),
                end_time_s=int(event.payload["end_time_s"]),
                max_traction_supply_kw=event.payload.get("max_traction_supply_kw"),
                max_regen_absorption_kw=event.payload.get("max_regen_absorption_kw"),
                max_grid_feedback_kw=event.payload.get("max_grid_feedback_kw"),
                reason=str(event.payload.get("reason") or ""),
            )
            for event in self.events
            if event.event_type == "power_arm_limit" and event.applicable
        )
        return RollingCycleObservation(
            observed_heavy_delay_s=self.observed_heavy_delay_s,
            observed_empty_delay_s=self.observed_empty_delay_s,
            observed_train_delays_s=tuple(
                (event.entity_id, int(event.payload["delay_s"]))
                for event in self.events
                if event.event_type == "train_delay" and event.applicable
            ),
            storage_device_states=(
                self.storage_device_states if self.storage_states_provided else ()
            ),
            cancelled_train_ids=cancelled,
            added_trains=additions,
            resource_unavailabilities=outages,
            dynamic_power_arm_limits=power_limits,
        )


@dataclass(frozen=True)
class HistoricalDisturbanceReplay:
    """经过校验、可确定性复算的历史扰动回放。"""

    replay_code: str
    data_status: str
    execute_window_s: int
    cycles: tuple[HistoricalDisturbanceCycle, ...]
    source_system: str = ""
    source_note: str = ""
    source_path: str = ""
    source_sha256: str = ""
    schema_version: str = SCHEMA_VERSION

    @property
    def observations(self) -> tuple[RollingCycleObservation, ...]:
        return tuple(cycle.to_observation() for cycle in self.cycles)

    @property
    def blocking_events(self) -> tuple[HistoricalDisturbanceEvent, ...]:
        return tuple(
            event for cycle in self.cycles for event in cycle.events
            if not event.applicable
        )

    def manifest(self) -> dict[str, Any]:
        """返回随结果发布的最小可追溯清单。"""

        return {
            "schema_version": self.schema_version,
            "replay_code": self.replay_code,
            "data_status": self.data_status,
            "source_system": self.source_system,
            "source_note": self.source_note,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "execute_window_s": self.execute_window_s,
            "cycle_count": len(self.cycles),
            "source_record_count": len({
                record_id for cycle in self.cycles for record_id in cycle.source_record_ids
            }),
            "event_count": sum(len(cycle.events) for cycle in self.cycles),
            "applied_event_count": sum(
                event.applicable for cycle in self.cycles for event in cycle.events
            ),
            "blocking_event_count": len(self.blocking_events),
            "first_current_time_s": self.cycles[0].current_time_s,
            "last_current_time_s": self.cycles[-1].current_time_s,
        }

    def preflight(self) -> dict[str, Any]:
        """返回平台可直接展示的事件受理和阻断明细。"""

        event_rows = []
        for cycle in self.cycles:
            for event in cycle.events:
                event_rows.append({
                    "cycle_index": cycle.cycle_index,
                    "current_time_s": cycle.current_time_s,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "entity_id": event.entity_id,
                    "status": "accepted" if event.applicable else "blocked",
                    "blocking_reason": event.blocking_reason,
                })
        return {
            "valid": True,
            "execution_allowed": not self.blocking_events,
            "manifest": self.manifest(),
            "events": event_rows,
        }


def _parse_storage_states(value: Any, field_name: str) -> tuple[StorageDeviceRuntimeState, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name}必须是非空JSON对象数组。")
    allowed = {
        "storage_section_id", "soc_kwh", "available",
        "max_charge_power_kw", "max_discharge_power_kw",
    }
    states = []
    for index, item in enumerate(value):
        item_name = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{item_name}必须是JSON对象。")
        _reject_unknown_fields(item, allowed, item_name)
        if "storage_section_id" not in item or "soc_kwh" not in item:
            raise ValueError(f"{item_name}必须包含storage_section_id和soc_kwh。")
        try:
            states.append(StorageDeviceRuntimeState(**item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{item_name}状态无效：{exc}") from exc
    normalized = normalize_storage_runtime_states(states)
    return tuple(normalized[key] for key in sorted(normalized))


def _parse_event(
    value: Any,
    field_name: str,
    *,
    enable_dynamic_execution: bool,
    enable_directional_speed_execution: bool,
) -> HistoricalDisturbanceEvent:
    """校验统一事件载荷，并区分可直接执行和等待业务规则的事件。"""

    if not isinstance(value, dict):
        raise ValueError(f"{field_name}必须是JSON对象。")
    _reject_unknown_fields(value, {"event_id", "event_type", "entity_id", "payload"}, field_name)
    event_id = _required_text(value.get("event_id"), f"{field_name}.event_id")
    event_type = _required_text(value.get("event_type"), f"{field_name}.event_type")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"{field_name}.event_type不在允许枚举中：{sorted(EVENT_TYPES)}")
    entity_id = _required_text(value.get("entity_id"), f"{field_name}.entity_id")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise ValueError(f"{field_name}.payload必须是JSON对象。")

    blocking_reason = ""
    if event_type == "train_delay":
        _reject_unknown_fields(payload, {"delay_s"}, f"{field_name}.payload")
        entity_id = _train_id(entity_id, f"{field_name}.entity_id")
        payload = {"delay_s": _whole_seconds(payload.get("delay_s"), f"{field_name}.payload.delay_s")}
    elif event_type == "train_cancelled":
        entity_id = _train_id(entity_id, f"{field_name}.entity_id")
        _reject_unknown_fields(payload, {"reason"}, f"{field_name}.payload")
        if not enable_dynamic_execution:
            blocking_reason = "schema_version 1.1仅登记取消事件；请升级到1.2执行。"
    elif event_type == "train_added":
        entity_id = _train_id(entity_id, f"{field_name}.entity_id")
        _reject_unknown_fields(payload, {"train_type", "departure_s", "reason"}, f"{field_name}.payload")
        train_type = _required_text(payload.get("train_type"), f"{field_name}.payload.train_type")
        if train_type not in {"Heavy", "Empty"}:
            raise ValueError(f"{field_name}.payload.train_type只能为Heavy或Empty。")
        payload = dict(payload)
        payload["train_type"] = train_type
        payload["departure_s"] = _whole_seconds(payload.get("departure_s"), f"{field_name}.payload.departure_s")
        if not enable_dynamic_execution:
            blocking_reason = "schema_version 1.1仅登记加车事件；请升级到1.2执行。"
    elif event_type == "temporary_speed_restriction":
        required = {"start_km", "end_km", "speed_limit_kmh", "start_time_s", "end_time_s"}
        _reject_unknown_fields(payload, required | {"direction", "reason"}, f"{field_name}.payload")
        if not required.issubset(payload):
            raise ValueError(f"{field_name}.payload缺少字段：{sorted(required - set(payload))}")
        payload = dict(payload)
        payload["start_km"] = _finite_number(payload["start_km"], f"{field_name}.payload.start_km", minimum=0)
        payload["end_km"] = _finite_number(payload["end_km"], f"{field_name}.payload.end_km", minimum=0)
        payload["speed_limit_kmh"] = _finite_number(payload["speed_limit_kmh"], f"{field_name}.payload.speed_limit_kmh", minimum=0)
        payload["start_time_s"] = _whole_seconds(payload["start_time_s"], f"{field_name}.payload.start_time_s")
        payload["end_time_s"] = _whole_seconds(payload["end_time_s"], f"{field_name}.payload.end_time_s")
        if payload["start_km"] == payload["end_km"] or payload["speed_limit_kmh"] <= 0 or payload["end_time_s"] <= payload["start_time_s"]:
            raise ValueError(f"{field_name}.payload限速区间、速度或时间窗无效。")
        try:
            direction = normalize_speed_restriction_direction(payload.get("direction"))
        except ValueError as exc:
            raise ValueError(f"{field_name}.payload.direction无效。") from exc
        if direction != "both" and not enable_directional_speed_execution:
            blocking_reason = "schema_version 1.2及以下仅登记方向专用限速；请升级到1.3执行。"
        payload["direction"] = direction
    elif event_type == "resource_unavailable":
        required = {"resource_type", "start_time_s", "end_time_s"}
        _reject_unknown_fields(payload, required | {"reason"}, f"{field_name}.payload")
        if not required.issubset(payload):
            raise ValueError(f"{field_name}.payload缺少字段：{sorted(required - set(payload))}")
        resource_type = _required_text(payload["resource_type"], f"{field_name}.payload.resource_type")
        if resource_type not in {"signaling_block", "segment", "station_track", "throat"}:
            raise ValueError(f"{field_name}.payload.resource_type无效。")
        payload = dict(payload)
        payload["resource_type"] = resource_type
        payload["start_time_s"] = _whole_seconds(payload["start_time_s"], f"{field_name}.payload.start_time_s")
        payload["end_time_s"] = _whole_seconds(payload["end_time_s"], f"{field_name}.payload.end_time_s")
        if payload["end_time_s"] <= payload["start_time_s"]:
            raise ValueError(f"{field_name}.payload时间窗必须非空。")
        if not enable_dynamic_execution:
            blocking_reason = "schema_version 1.1仅登记资源封锁；请升级到1.2执行。"
    elif event_type == "power_arm_limit":
        allowed = {"max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw", "start_time_s", "end_time_s", "reason"}
        _reject_unknown_fields(payload, allowed, f"{field_name}.payload")
        if not {"start_time_s", "end_time_s"}.issubset(payload):
            raise ValueError(f"{field_name}.payload必须包含start_time_s和end_time_s。")
        if not {
            "max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw"
        }.intersection(payload):
            raise ValueError(f"{field_name}.payload至少需要一个动态功率限值。")
        payload = dict(payload)
        for name in allowed & set(payload) - {"reason", "start_time_s", "end_time_s"}:
            payload[name] = _finite_number(payload[name], f"{field_name}.payload.{name}", minimum=0)
        payload["start_time_s"] = _whole_seconds(payload["start_time_s"], f"{field_name}.payload.start_time_s")
        payload["end_time_s"] = _whole_seconds(payload["end_time_s"], f"{field_name}.payload.end_time_s")
        if payload["end_time_s"] <= payload["start_time_s"]:
            raise ValueError(f"{field_name}.payload时间窗必须非空。")
        if not enable_dynamic_execution:
            blocking_reason = "schema_version 1.1仅登记动态供电限值；请升级到1.2执行。"
    else:
        _reject_unknown_fields(payload, {"soc_kwh", "available", "max_charge_power_kw", "max_discharge_power_kw"}, f"{field_name}.payload")
        if "soc_kwh" not in payload:
            raise ValueError(f"{field_name}.payload必须包含soc_kwh。")
        try:
            StorageDeviceRuntimeState(storage_section_id=entity_id, **payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}.payload设备状态无效：{exc}") from exc

    return HistoricalDisturbanceEvent(
        event_id=event_id,
        event_type=event_type,
        entity_id=entity_id,
        payload=payload,
        applicable=not blocking_reason,
        blocking_reason=blocking_reason,
    )


def parse_historical_disturbance_replay(
    payload: Any,
    *,
    source_path: str = "",
    source_sha256: str = "",
) -> HistoricalDisturbanceReplay:
    """严格解析回放JSON；任何无法解释的数据都会在求解前被拒绝。"""

    if not isinstance(payload, dict):
        raise ValueError("历史扰动回放根节点必须是JSON对象。")
    _reject_unknown_fields(payload, {
        "schema_version", "replay_code", "data_status", "execute_window_s",
        "cycles", "source_system", "source_note",
    }, "历史扰动回放")
    schema_version = _required_text(payload.get("schema_version"), "schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"不支持的历史扰动回放schema_version：{schema_version!r}，当前支持{sorted(SUPPORTED_SCHEMA_VERSIONS)}。"
        )
    replay_code = _required_text(payload.get("replay_code"), "replay_code")
    data_status = _required_text(payload.get("data_status"), "data_status")
    if data_status not in DATA_STATUS_VALUES:
        raise ValueError(f"data_status不在允许枚举中：{sorted(DATA_STATUS_VALUES)}")
    execute_window_s = _whole_seconds(payload.get("execute_window_s"), "execute_window_s")
    if execute_window_s <= 0:
        raise ValueError("execute_window_s必须大于0。")
    cycle_rows = payload.get("cycles")
    if not isinstance(cycle_rows, list) or len(cycle_rows) < 2:
        raise ValueError("历史扰动回放至少需要两个cycles记录。")

    cycles = []
    all_source_ids: set[str] = set()
    all_event_ids: set[str] = set()
    previous_observed_at: datetime | None = None
    cycle_allowed = {
        "cycle_index", "current_time_s", "observed_heavy_delay_s",
        "observed_empty_delay_s", "source_record_ids", "observed_at",
        "storage_devices",
        "events",
    }
    for index, row in enumerate(cycle_rows):
        field_name = f"cycles[{index}]"
        if not isinstance(row, dict):
            raise ValueError(f"{field_name}必须是JSON对象。")
        _reject_unknown_fields(row, cycle_allowed, field_name)
        cycle_index = _whole_seconds(row.get("cycle_index"), f"{field_name}.cycle_index")
        if cycle_index != index:
            raise ValueError(f"{field_name}.cycle_index必须连续且从0开始。")
        current_time_s = _whole_seconds(row.get("current_time_s"), f"{field_name}.current_time_s")
        expected_time_s = index * execute_window_s
        if current_time_s != expected_time_s:
            raise ValueError(
                f"{field_name}.current_time_s必须等于{expected_time_s}，以匹配固定滚动窗口。"
            )
        raw_ids = row.get("source_record_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError(f"{field_name}.source_record_ids必须是非空字符串数组。")
        source_ids = tuple(_required_text(value, f"{field_name}.source_record_ids") for value in raw_ids)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError(f"{field_name}.source_record_ids不能重复。")
        duplicates = all_source_ids.intersection(source_ids)
        if duplicates:
            raise ValueError(f"历史源记录ID不能跨周期重复：{sorted(duplicates)}")
        all_source_ids.update(source_ids)
        storage_provided = "storage_devices" in row
        storage_states = (
            _parse_storage_states(row["storage_devices"], f"{field_name}.storage_devices")
            if storage_provided else ()
        )
        raw_events = row.get("events", [])
        if not isinstance(raw_events, list):
            raise ValueError(f"{field_name}.events必须是JSON对象数组。")
        if schema_version == "1.0" and raw_events:
            raise ValueError("schema_version 1.0不支持events；请升级到1.1。")
        events = tuple(
            _parse_event(
                item,
                f"{field_name}.events[{event_index}]",
                enable_dynamic_execution=schema_version in {"1.2", SCHEMA_VERSION},
                enable_directional_speed_execution=schema_version == SCHEMA_VERSION,
            )
            for event_index, item in enumerate(raw_events)
        )
        cycle_event_ids = [event.event_id for event in events]
        if len(set(cycle_event_ids)) != len(cycle_event_ids):
            raise ValueError(f"{field_name}.event_id不能在同一周期重复。")
        duplicate_event_ids = all_event_ids.intersection(event.event_id for event in events)
        if duplicate_event_ids:
            raise ValueError(f"历史事件ID不能重复：{sorted(duplicate_event_ids)}")
        all_event_ids.update(event.event_id for event in events)
        train_delay_ids = [
            event.entity_id for event in events if event.event_type == "train_delay"
        ]
        if len(set(train_delay_ids)) != len(train_delay_ids):
            raise ValueError(f"{field_name}不能为同一列车重复提供train_delay事件。")
        cancelled_ids = {
            event.entity_id for event in events if event.event_type == "train_cancelled"
        }
        added_ids = [event.entity_id for event in events if event.event_type == "train_added"]
        if len(set(added_ids)) != len(added_ids):
            raise ValueError(f"{field_name}不能重复加开同一列车。")
        contradictory = cancelled_ids.intersection(train_delay_ids).union(cancelled_ids.intersection(added_ids))
        if contradictory:
            raise ValueError(f"{field_name}同一列车不能同时取消并晚点/加开：{sorted(contradictory)}")
        for event in events:
            if event.event_type == "train_added" and int(event.payload["departure_s"]) < current_time_s:
                raise ValueError(f"{field_name}不能加开早于当前周期的列车：{event.entity_id}")
            if event.event_type in {"resource_unavailable", "power_arm_limit"} and int(event.payload["end_time_s"]) <= current_time_s:
                raise ValueError(f"{field_name}不能提交已经失效的{event.event_type}事件：{event.event_id}")
        storage_events = tuple(
            event for event in events if event.event_type == "storage_device_state"
        )
        if storage_events:
            if storage_provided:
                raise ValueError(
                    f"{field_name}不能同时提供storage_devices和storage_device_state事件。"
                )
            storage_states = _parse_storage_states(
                [
                    {"storage_section_id": event.entity_id, **dict(event.payload)}
                    for event in storage_events
                ],
                f"{field_name}.events.storage_device_state",
            )
            storage_provided = True
        train_delay_directions = {event.entity_id[0] for event in events if event.event_type == "train_delay" and int(event.payload["delay_s"]) > 0}
        observed_at, parsed_observed_at = _zoned_timestamp(
            row.get("observed_at"), f"{field_name}.observed_at"
        )
        if previous_observed_at is not None and parsed_observed_at <= previous_observed_at:
            raise ValueError(f"{field_name}.observed_at必须按周期严格递增。")
        previous_observed_at = parsed_observed_at
        cycles.append(HistoricalDisturbanceCycle(
            cycle_index=cycle_index,
            current_time_s=current_time_s,
            observed_heavy_delay_s=_whole_seconds(
                row.get("observed_heavy_delay_s"), f"{field_name}.observed_heavy_delay_s"
            ),
            observed_empty_delay_s=_whole_seconds(
                row.get("observed_empty_delay_s"), f"{field_name}.observed_empty_delay_s"
            ),
            source_record_ids=source_ids,
            observed_at=observed_at,
            storage_device_states=storage_states,
            storage_states_provided=storage_provided,
            events=events,
        ))
        if cycles[-1].observed_heavy_delay_s and "H" in train_delay_directions:
            raise ValueError(f"{field_name}不能同时提供重车汇总晚点和重车逐列车晚点。")
        if cycles[-1].observed_empty_delay_s and "E" in train_delay_directions:
            raise ValueError(f"{field_name}不能同时提供空车汇总晚点和空车逐列车晚点。")
    return HistoricalDisturbanceReplay(
        replay_code=replay_code,
        data_status=data_status,
        execute_window_s=execute_window_s,
        cycles=tuple(cycles),
        source_system=str(payload.get("source_system") or "").strip(),
        source_note=str(payload.get("source_note") or "").strip(),
        source_path=source_path,
        source_sha256=source_sha256,
        schema_version=schema_version,
    )


def load_historical_disturbance_replay(
    path: Path,
    *,
    source_label: str | None = None,
) -> HistoricalDisturbanceReplay:
    """从文件读取回放，并保留源路径与内容摘要。"""

    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"历史扰动回放文件不是有效UTF-8 JSON：{path}") from exc
    return parse_historical_disturbance_replay(
        payload,
        source_path=str(source_label if source_label is not None else path),
        source_sha256=sha256(raw).hexdigest(),
    )
