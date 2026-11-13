"""实时列车状态的校验、可信游标和断流恢复守卫。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping, Sequence


def _finite(value: Any, field_name: str) -> float:
    """把输入转换为有限浮点数，并拒绝布尔值。"""

    if isinstance(value, bool):
        raise ValueError(f"{field_name}必须是有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name}必须是有限数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name}必须是有限数值")
    return number


def _whole_nonnegative(value: Any, field_name: str) -> int:
    """校验非负整数秒。"""

    number = _finite(value, field_name)
    if number < 0 or not number.is_integer():
        raise ValueError(f"{field_name}必须是非负整数")
    return int(number)


def validate_realtime_snapshot(
    snapshot: Mapping[str, Any],
    *,
    capacity_kwh: float | None = None,
) -> None:
    """校验单条实时列车状态的字段、类型和数值范围。"""

    if not isinstance(snapshot, Mapping):
        raise ValueError("实时状态必须是对象")
    required = (
        "timestamp_s",
        "train_id",
        "direction",
        "position_km",
        "speed_mps",
        "power_kW",
    )
    missing = [key for key in required if key not in snapshot]
    if missing:
        raise ValueError(f"缺少实时字段：{missing}")
    _whole_nonnegative(snapshot["timestamp_s"], "timestamp_s")
    if not str(snapshot["train_id"]).strip():
        raise ValueError("train_id不能为空")
    if snapshot["direction"] not in {"forward", "reverse"}:
        raise ValueError("direction必须是forward或reverse")
    if _finite(snapshot["position_km"], "position_km") < 0:
        raise ValueError("position_km不能为负数")
    if _finite(snapshot["speed_mps"], "speed_mps") < 0:
        raise ValueError("speed_mps不能为负数")
    _finite(snapshot["power_kW"], "power_kW")
    if "soc_kwh" in snapshot:
        soc_kwh = _finite(snapshot["soc_kwh"], "soc_kwh")
        if soc_kwh < 0:
            raise ValueError("soc_kwh不能为负数")
        if capacity_kwh is not None:
            capacity = _finite(capacity_kwh, "capacity_kwh")
            if capacity < 0:
                raise ValueError("capacity_kwh不能为负数")
            if soc_kwh > capacity + 1e-9:
                raise ValueError("soc_kwh超过容量上限")


@dataclass(frozen=True)
class RealtimeGuardPolicy:
    """实时消息新鲜度和断流阈值。"""

    max_staleness_s: int = 30
    max_future_skew_s: int = 5
    outage_timeout_s: int = 30

    def __post_init__(self) -> None:
        for field_name in (
            "max_staleness_s",
            "max_future_skew_s",
            "outage_timeout_s",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name}必须是非负整数")


class RealtimeStateGuard:
    """只用通过全部门禁的消息推进逐列车可信游标。"""

    def __init__(
        self,
        policy: RealtimeGuardPolicy | None = None,
        *,
        capacity_kwh: float | None = None,
        expected_train_ids: Iterable[str] = (),
    ) -> None:
        self.policy = policy or RealtimeGuardPolicy()
        self.capacity_kwh = capacity_kwh
        normalized_ids = [str(value).strip() for value in expected_train_ids]
        if any(not value for value in normalized_ids):
            raise ValueError("expected_train_ids不能包含空值")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("expected_train_ids不能重复")
        self.expected_train_ids = tuple(sorted(normalized_ids))
        self._cursor: dict[str, dict[str, Any]] = {}
        self._last_records: dict[str, dict[str, Any]] = {}
        self._latest_accepted_timestamp_s: int | None = None
        self._ever_healthy = False

    def _health(self, now_s: int) -> dict[str, Any]:
        """根据最后一条可信消息判断实时输入是否可用于新决策。"""

        missing_train_ids = [
            train_id for train_id in self.expected_train_ids if train_id not in self._cursor
        ]
        stale_train_ids = [
            train_id
            for train_id in self.expected_train_ids
            if train_id in self._cursor
            and now_s - int(self._cursor[train_id]["timestamp_s"])
            > self.policy.outage_timeout_s
        ]
        if self._latest_accepted_timestamp_s is None:
            return {
                "state": "no_data_hold",
                "action": "hold_and_wait_for_snapshot",
                "age_s": None,
                "missing_train_ids": missing_train_ids,
                "stale_train_ids": stale_train_ids,
            }
        if missing_train_ids:
            return {
                "state": "incomplete_stream_hold",
                "action": "hold_new_decisions_and_wait_for_complete_snapshot",
                "age_s": now_s - self._latest_accepted_timestamp_s,
                "missing_train_ids": missing_train_ids,
                "stale_train_ids": stale_train_ids,
            }
        if stale_train_ids:
            return {
                "state": "stream_outage_hold",
                "action": "hold_new_decisions_and_keep_last_trusted_state",
                "age_s": now_s - self._latest_accepted_timestamp_s,
                "missing_train_ids": missing_train_ids,
                "stale_train_ids": stale_train_ids,
            }
        age_s = now_s - self._latest_accepted_timestamp_s
        if age_s > self.policy.outage_timeout_s:
            return {
                "state": "stream_outage_hold",
                "action": "hold_new_decisions_and_keep_last_trusted_state",
                "age_s": age_s,
                "missing_train_ids": missing_train_ids,
                "stale_train_ids": stale_train_ids,
            }
        return {
            "state": "healthy",
            "action": "use_accepted_snapshot",
            "age_s": age_s,
            "missing_train_ids": missing_train_ids,
            "stale_train_ids": stale_train_ids,
        }

    def evaluate(self, now_s: int) -> dict[str, Any]:
        """在没有新消息时检查断流状态，不改变可信游标。"""

        now = _whole_nonnegative(now_s, "now_s")
        result = self._health(now)
        return {**result, "cursor": self.cursor_snapshot()}

    def cursor_snapshot(self) -> dict[str, dict[str, Any]]:
        """返回可序列化的可信游标副本。"""

        return {train_id: dict(value) for train_id, value in sorted(self._cursor.items())}

    def ingest_batch(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        received_at_s: int,
    ) -> dict[str, Any]:
        """按接收顺序校验消息；任何失败消息都不得污染后续状态。"""

        received_at = _whole_nonnegative(received_at_s, "received_at_s")
        before = self._health(received_at)
        accepted_indices: list[int] = []
        errors: list[dict[str, Any]] = []

        for index, row in enumerate(rows):
            try:
                validate_realtime_snapshot(row, capacity_kwh=self.capacity_kwh)
                timestamp_s = int(float(row["timestamp_s"]))
                train_id = str(row["train_id"]).strip()
                direction = str(row["direction"])
                position_km = float(row["position_km"])
                if self.expected_train_ids and train_id not in self.expected_train_ids:
                    raise ValueError("列车ID不在期望状态集合中")
                age_s = received_at - timestamp_s
                if age_s > self.policy.max_staleness_s:
                    raise ValueError("消息已超过最大新鲜度")
                if timestamp_s - received_at > self.policy.max_future_skew_s:
                    raise ValueError("消息时间超过允许的未来时钟偏差")

                previous = self._cursor.get(train_id)
                if previous is not None:
                    if timestamp_s == previous["timestamp_s"]:
                        if dict(row) == self._last_records[train_id]:
                            raise ValueError("重复消息")
                        raise ValueError("同一列车时间戳重复但内容不一致")
                    if timestamp_s < previous["timestamp_s"]:
                        raise ValueError("同一列车消息乱序")
                    if direction != previous["direction"]:
                        raise ValueError("同一列车方向发生变化")
                    if direction == "forward" and position_km < previous["position_km"] - 1e-9:
                        raise ValueError("正向列车位置倒退")
                    if direction == "reverse" and position_km > previous["position_km"] + 1e-9:
                        raise ValueError("反向列车位置前进")

                self._cursor[train_id] = {
                    "timestamp_s": timestamp_s,
                    "position_km": position_km,
                    "direction": direction,
                }
                self._last_records[train_id] = dict(row)
                self._latest_accepted_timestamp_s = max(
                    timestamp_s,
                    self._latest_accepted_timestamp_s
                    if self._latest_accepted_timestamp_s is not None
                    else timestamp_s,
                )
                accepted_indices.append(index)
            except (TypeError, ValueError) as exc:
                errors.append({"index": index, "error": str(exc)})

        after = self._health(received_at)
        recovered = (
            self._ever_healthy
            and before["state"] != "healthy"
            and after["state"] == "healthy"
            and bool(accepted_indices)
        )
        if after["state"] == "healthy":
            self._ever_healthy = True
        return {
            "valid": not errors,
            "row_count": len(rows),
            "accepted_count": len(accepted_indices),
            "rejected_count": len(errors),
            "accepted_indices": accepted_indices,
            "errors": errors,
            "state_before": before["state"],
            "state": "recovered" if recovered else after["state"],
            "action": after["action"],
            "recovered": recovered,
            "missing_train_ids": list(after["missing_train_ids"]),
            "stale_train_ids": list(after["stale_train_ids"]),
            "cursor": self.cursor_snapshot(),
        }


def validate_realtime_batch(
    rows: Sequence[Mapping[str, Any]],
    *,
    capacity_kwh: float | None = None,
) -> dict[str, Any]:
    """兼容旧批次接口，只检查字段和逐列车顺序，不施加接收时钟门禁。"""

    cursor: dict[str, tuple[int, float, str]] = {}
    errors: list[dict[str, Any]] = []
    accepted_indices: list[int] = []
    for index, row in enumerate(rows):
        try:
            validate_realtime_snapshot(row, capacity_kwh=capacity_kwh)
            train_id = str(row["train_id"]).strip()
            timestamp_s = int(float(row["timestamp_s"]))
            position_km = float(row["position_km"])
            direction = str(row["direction"])
            previous = cursor.get(train_id)
            if previous is not None:
                old_timestamp_s, old_position_km, old_direction = previous
                if timestamp_s <= old_timestamp_s:
                    raise ValueError("同一列车时间戳必须严格递增")
                if direction != old_direction:
                    raise ValueError("同一列车方向不能变化")
                if direction == "forward" and position_km < old_position_km - 1e-9:
                    raise ValueError("正向列车位置不能倒退")
                if direction == "reverse" and position_km > old_position_km + 1e-9:
                    raise ValueError("反向列车位置不能前进")
            cursor[train_id] = (timestamp_s, position_km, direction)
            accepted_indices.append(index)
        except (TypeError, ValueError) as exc:
            errors.append({"index": index, "error": str(exc)})
    return {
        "valid": not errors,
        "row_count": len(rows),
        "accepted_count": len(accepted_indices),
        "rejected_count": len(errors),
        "accepted_indices": accepted_indices,
        "error_count": len(errors),
        "errors": errors,
    }
