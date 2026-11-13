# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_settlement import (
    EnergyBucketRequest,
    EnergySettlementSystem,
    build_power_series,
    initialize_storage_settlement_state,
    storage_no_direct_effective_loss_kwh,
    settle_energy_bucket_group,
)
from power_arm_electrical_limits import PowerArmElectricalLimit
from train_simulator import BatteryStorageParameters, StepRecord, StorageDeviceParameters


def _battery(**kwargs) -> BatteryStorageParameters:
    """函数 _battery：执行该模块中的相关处理逻辑。"""
    base = dict(
        capacity_kwh=100.0,
        round_trip_efficiency=1.0,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=1.0,
        max_charge_power_kW=1e9,
        max_discharge_power_kW=1e9,
    )
    base.update(kwargs)
    return BatteryStorageParameters(**base)


def test_non_finite_power_raises() -> None:
    """函数 test_non_finite_power_raises：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": PowerArmElectricalLimit(storage_available=True, storage_section_id="S")},
    )
    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            system.settle([{0: (bad, 1.0, "A1", 10.0, "S")}])
        except ValueError as exc:
            if "finite" not in str(exc):
                raise AssertionError(f"unexpected error for {bad}: {exc}") from exc
        else:
            raise AssertionError(f"expected ValueError for non-finite power {bad}")


def test_device_self_discharge_is_applied_per_elapsed_bucket() -> None:
    device = StorageDeviceParameters(
        storage_section_id="S",
        capacity_kwh=100.0,
        max_charge_power_kw=100.0,
        max_discharge_power_kw=100.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        initial_soc_kwh=100.0,
        min_soc_kwh=0.0,
        max_soc_kwh=100.0,
        self_discharge_rate_per_hour=0.1,
    )
    battery = _battery(
        capacity_kwh=100.0,
        max_charge_power_kW=100.0,
        max_discharge_power_kW=100.0,
        storage_devices=(device,),
    )
    system = EnergySettlementSystem(
        battery=battery,
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": PowerArmElectricalLimit(storage_available=True, storage_section_id="S")},
    )
    result = system.settle([
        {
            0: (0.0, 1.0, "A1", 3600.0, "S"),
            3600: (0.0, 1.0, "A1", 3600.0, "S"),
        }
    ])
    if abs(result.final_soc_kwh - 81.0) > 1e-9:
        raise AssertionError(result)
    if abs(result.self_discharge_loss_kwh - 19.0) > 1e-9:
        raise AssertionError(result)
    if abs(result.self_discharge_loss_by_storage_kwh["S"] - 19.0) > 1e-9:
        raise AssertionError(result)


def test_charge_limited_allocated_by_charge_capacity() -> None:
    """Unmet charge desire must not be attributed beyond each arm's charge capacity."""

    storage_state = initialize_storage_settlement_state(
        ["S"],
        capacity_kwh=100.0,
        max_charge_power_kw=18.0,  # 0.05 kWh over 10s
        max_discharge_power_kw=1e9,
        initial_soc_kwh=0.0,
        efficiency=1.0,
    )
    lim_hi = PowerArmElectricalLimit(
        max_regen_absorption_kw=1e9,
        storage_available=True,
        storage_section_id="S",
    )
    lim_lo = PowerArmElectricalLimit(
        max_regen_absorption_kw=36.0,  # 0.1 kWh over 10s
        storage_available=True,
        storage_section_id="S",
    )
    requests = [
        EnergyBucketRequest(0.0, 1.0, 0.0, 0.0, 0, 10, "S", lim_hi),
        EnergyBucketRequest(0.0, 1.0, 0.0, 0.0, 0, 10, "S", lim_lo),
    ]
    out = settle_energy_bucket_group(
        requests,
        allow_direct_use=False,
        allow_storage=True,
        storage_state=storage_state,
    )
    if out[1].battery_charge_limited_kwh > 0.1 + 1e-9:
        raise AssertionError(
            "low-room arm received charge_limited above its charge capacity: "
            f"{out[1].battery_charge_limited_kwh}"
        )
    limited_total = sum(item.battery_charge_limited_kwh for item in out)
    if abs(limited_total - 1.05) > 1e-9:
        raise AssertionError(f"expected limited total 1.05, got {limited_total}")
    if abs(sum(item.battery_charge_kwh for item in out) - 0.05) > 1e-9:
        raise AssertionError(out)


def test_multi_bin_energy_and_capacity() -> None:
    """函数 test_multi_bin_energy_and_capacity：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=_battery(capacity_kwh=1.0),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": PowerArmElectricalLimit(storage_available=True, storage_section_id="SEC1")},
        initial_soc_kwh=0.0,
    )
    series = {
        0: (-360.0, 1.0, "A1", 10.0, "SEC1"),
        10: (-360.0, 1.0, "A1", 10.0, "SEC1"),
    }
    result = system.settle([series])
    if abs(result.battery_charge_kwh - 1.0) > 1e-9 or abs(result.wasted_kwh - 1.0) > 1e-9:
        raise AssertionError(
            f"capacity fill mismatch charge={result.battery_charge_kwh} wasted={result.wasted_kwh}"
        )


def test_zero_storage_power_disables_charge_and_discharge() -> None:
    """An unavailable device must not be interpreted as unlimited storage."""

    system = EnergySettlementSystem(
        battery=_battery(
            capacity_kwh=10.0,
            max_charge_power_kW=0.0,
            max_discharge_power_kW=0.0,
        ),
        settlement_time_step_s=3600,
        initial_soc_kwh=5.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A1": PowerArmElectricalLimit(
                storage_available=True,
                storage_section_id="S",
            )
        },
    )
    result = system.settle(
        [
            {
                0: (-10.0, 1.0, "A1", 3600.0, "S"),
                3600: (10.0, 1.0, "A1", 3600.0, "S"),
            }
        ]
    )
    if result.battery_charge_kwh != 0.0 or result.battery_discharge_kwh != 0.0:
        raise AssertionError(f"zero-power storage moved energy: {result}")
    if abs(result.wasted_kwh - 10.0) > 1e-9 or abs(result.grid_kwh - 10.0) > 1e-9:
        raise AssertionError(result)
    if abs(result.final_soc_kwh - 5.0) > 1e-9:
        raise AssertionError(result)


def test_zero_efficiency_disables_initial_soc_discharge() -> None:
    """Zero-efficiency storage cannot return even pre-existing inventory."""

    system = EnergySettlementSystem(
        battery=_battery(
            capacity_kwh=10.0,
            round_trip_efficiency=0.0,
            max_charge_power_kW=10000.0,
            max_discharge_power_kW=10000.0,
        ),
        settlement_time_step_s=3600,
        initial_soc_kwh=5.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A1": PowerArmElectricalLimit(
                storage_available=True,
                storage_section_id="S",
            )
        },
    )
    result = system.settle([{0: (10.0, 1.0, "A1", 3600.0, "S")}])
    if result.battery_discharge_kwh != 0.0:
        raise AssertionError(
            f"zero-efficiency storage discharged initial SOC: {result.battery_discharge_kwh}"
        )
    if abs(result.grid_kwh - 10.0) > 1e-9 or abs(result.final_soc_kwh - 5.0) > 1e-9:
        raise AssertionError(result)


def test_storage_tag_cannot_override_unavailable_power_arm() -> None:
    """函数 test_storage_tag_cannot_override_unavailable_power_arm：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=_battery(capacity_kwh=100.0),
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": PowerArmElectricalLimit(storage_available=False)},
    )
    result = system.settle([{0: (-10.0, 1.0, "A1", 3600.0, "STALE_TAG")}])
    if result.battery_charge_kwh != 0.0 or abs(result.wasted_kwh - 10.0) > 1e-9:
        raise AssertionError(f"unavailable storage absorbed energy: {result}")

    mismatched = EnergySettlementSystem(
        battery=_battery(capacity_kwh=100.0),
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A1": PowerArmElectricalLimit(
                storage_available=True,
                storage_section_id="EXPECTED",
            )
        },
    )
    try:
        mismatched.settle([{0: (-10.0, 1.0, "A1", 3600.0, "STALE_TAG")}])
    except ValueError as exc:
        if "not enabled" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("mismatched storage geometry and power-arm status were accepted")


def test_storage_does_not_charge_and_discharge_in_same_bucket() -> None:
    """函数 test_storage_does_not_charge_and_discharge_in_same_bucket：执行该模块中的相关处理逻辑。"""
    state = initialize_storage_settlement_state(
        ["S"], 100.0, 1e9, 1e9, 0.0, 1.0
    )
    limit = PowerArmElectricalLimit(storage_available=True, storage_section_id="S")
    result = settle_energy_bucket_group(
        [EnergyBucketRequest(50.0, 100.0, 0.0, 0.0, 0, 10, "S", limit, "A")],
        allow_direct_use=False,
        allow_storage=True,
        storage_state=state,
    )[0]
    if result.battery_charge_kwh != 100.0 or result.battery_discharge_kwh != 0.0:
        raise AssertionError(f"same-bucket charge/discharge was not excluded: {result}")
    if result.soc_before_kwh != 0.0 or result.soc_after_kwh != 100.0:
        raise AssertionError(result)
    if result.grid_kwh != 50.0:
        raise AssertionError("newly charged energy incorrectly served same-bucket traction")


def test_simultaneous_group_requires_identical_positive_window() -> None:
    """函数 test_simultaneous_group_requires_identical_positive_window：执行该模块中的相关处理逻辑。"""
    storage_state = initialize_storage_settlement_state(
        ["S"], 100.0, 10.0, 10.0, 0.0, 1.0
    )
    limit = PowerArmElectricalLimit(storage_available=True, storage_section_id="S")
    mismatched = [
        EnergyBucketRequest(0.0, 1.0, 0.0, 0.0, 0, 10, "S", limit),
        EnergyBucketRequest(0.0, 1.0, 0.0, 0.0, 1000, 1010, "S", limit),
    ]
    try:
        settle_energy_bucket_group(
            mismatched,
            allow_direct_use=False,
            allow_storage=True,
            storage_state=storage_state,
        )
    except ValueError as exc:
        if "identical time window" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("non-simultaneous requests shared one battery power budget")

    invalid_window = [EnergyBucketRequest(0.0, 1.0, 0.0, 0.0, 10, 10, "S", limit)]
    try:
        settle_energy_bucket_group(
            invalid_window,
            allow_direct_use=False,
            allow_storage=True,
            storage_state=storage_state,
        )
    except ValueError as exc:
        if "end_s > start_s" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("zero-duration settlement window was accepted")


def test_invalid_sample_time_rejected() -> None:
    """函数 test_invalid_sample_time_rejected：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A1": PowerArmElectricalLimit(storage_available=True, storage_section_id="S")
        },
    )
    for series, expected_field in (
        ({0: (-360.0, 1.0, "A1", -10.0, "S")}, "sample_duration_s"),
        ({0: (-360.0, 1.0, "A1", 0.0, "S")}, "sample_duration_s"),
        ({float("nan"): (-360.0, 1.0, "A1", 10.0, "S")}, "time_s"),
        ({-1: (-360.0, 1.0, "A1", 10.0, "S")}, "time_s"),
        ({0.5: (-360.0, 1.0, "A1", 10.0, "S")}, "time_s"),
        ({0: (-360.0, -0.1, "A1", 10.0, "S")}, "transfer_ratio"),
        ({0: (-360.0, 1.1, "A1", 10.0, "S")}, "transfer_ratio"),
        ({0: (True, 1.0, "A1", 10.0, "S")}, "power_kW"),
        ({0: (-360.0, True, "A1", 10.0, "S")}, "transfer_ratio"),
        ({0: (-360.0, 1.0, "A1", True, "S")}, "sample_duration_s"),
        ({True: (-360.0, 1.0, "A1", 10.0, "S")}, "time_s"),
    ):
        try:
            system.settle([series])
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid power sample was silently discarded: {series!r}")


def test_effective_loss_rejects_invalid_numeric_inputs() -> None:
    """函数 test_effective_loss_rejects_invalid_numeric_inputs：执行该模块中的相关处理逻辑。"""
    for field_index, invalid_value in (
        (0, True),
        (0, -1.0),
        (1, float("nan")),
        (2, -1.0),
        (3, float("inf")),
    ):
        values = [1.0, 1.0, 1.0, 1.0]
        values[field_index] = invalid_value
        try:
            storage_no_direct_effective_loss_kwh(*values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid effective-loss input was accepted: {values!r}")
    for invalid_efficiency in (-1.0, 1.1, float("nan")):
        try:
            storage_no_direct_effective_loss_kwh(1.0, 1.0, 0.0, 1.0, invalid_efficiency)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"invalid storage efficiency was accepted: {invalid_efficiency!r}"
            )
    assert storage_no_direct_effective_loss_kwh(0.0, 10.0, 0.0, 9.0, 0.9) == 10.0
    assert storage_no_direct_effective_loss_kwh(0.0, 0.0, 5.0, 5.0, 0.9, 5.0) == 5.0


def test_effective_loss_counts_round_trip_efficiency_loss() -> None:
    """A charge/discharge cycle below 100% efficiency cannot look lossless."""

    # 产生 100 kWh 再生能量，随后由效率 90% 的储能设备输出 90 kWh。
    # 没有能量弃用，终端 SOC 恢复到参考值，但储能转换损失了 10 kWh。
    loss = storage_no_direct_effective_loss_kwh(
        wasted_kwh=0.0,
        battery_charge_kwh=100.0,
        battery_discharge_kwh=90.0,
        final_soc_deviation_kwh=0.0,
        storage_efficiency=0.9,
    )
    if abs(loss - 10.0) > 1e-9:
        raise AssertionError(f"round-trip efficiency loss was omitted: {loss}")


def test_effective_loss_preserves_conversion_loss_when_initial_soc_is_discharged() -> None:
    """Initial inventory must not hide conversion loss from new regeneration."""

    # 初始 SOC=50，随后 10 kWh 再生能量进入效率 90% 的储能设备，并放出 15 kWh。
    # 其中只有 9 kWh 可由新再生能量支撑，剩余 6 kWh 消耗初始库存；
    # 因此有效损失为 1 kWh 转换损失加 6 kWh 终端缺口。
    loss = storage_no_direct_effective_loss_kwh(
        wasted_kwh=0.0,
        battery_charge_kwh=10.0,
        battery_discharge_kwh=15.0,
        final_soc_deviation_kwh=6.0,
        storage_efficiency=0.9,
        final_soc_shortfall_kwh=6.0,
    )
    if abs(loss - 7.0) > 1e-9:
        raise AssertionError(
            "initial SOC discharge hid conversion loss: "
            f"expected 7.0, got {loss}"
        )

    # 通过真实能量结算流程验证同一个反例。
    limit = PowerArmElectricalLimit(
        storage_available=True,
        storage_section_id="S",
        max_traction_supply_kw=1e9,
        max_regen_absorption_kw=1e9,
    )
    result = EnergySettlementSystem(
        battery=_battery(round_trip_efficiency=0.9),
        settlement_time_step_s=10,
        initial_soc_kwh=50.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A": limit},
    ).settle(
        [
            {0: (-3600.0, 1.0, "A", 10.0, "S")},
            {10: (5400.0, 1.0, "A", 10.0, "S")},
        ]
    )
    pipeline_loss = storage_no_direct_effective_loss_kwh(
        result.wasted_kwh,
        result.battery_charge_kwh,
        result.battery_discharge_kwh,
        abs(result.final_soc_kwh - result.initial_soc_kwh),
        0.9,
        max(0.0, result.initial_soc_kwh - result.final_soc_kwh),
    )
    if abs(pipeline_loss - 7.0) > 1e-9 or abs(result.final_soc_kwh - 44.0) > 1e-9:
        raise AssertionError(
            "settlement pipeline misreported mixed initial-SOC loss: "
            f"loss={pipeline_loss}, final_soc={result.final_soc_kwh}"
        )


def test_effective_loss_isolated_per_storage_device() -> None:
    """Flows from independent storage devices must not be cross-credited."""

    limits = {
        "A1": PowerArmElectricalLimit(
            max_traction_supply_kw=1e9,
            max_regen_absorption_kw=1e9,
            storage_available=True,
            storage_section_id="S1",
        ),
        "A2": PowerArmElectricalLimit(
            max_traction_supply_kw=1e9,
            max_regen_absorption_kw=1e9,
            storage_available=True,
            storage_section_id="S2",
        ),
    }
    result = EnergySettlementSystem(
        battery=_battery(round_trip_efficiency=0.9),
        settlement_time_step_s=10,
        initial_soc_kwh=20.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=limits,
    ).settle(
        [
            # S1 接收新再生能量并将其保留在储能中。
            {0: (-3600.0, 1.0, "A1", 10.0, "S1")},
            # S2 仅释放结算开始前已有的库存。
            {10: (3600.0, 1.0, "A2", 10.0, "S2")},
        ]
    )
    # 初始 SOC 按 10/10 分配。S1 的 10 kWh 再生能量未被再利用；
    # S2 的 10 kWh 初始库存被消耗。有效损失总计为 20 kWh。
    if abs(result.effective_regen_loss_kwh - 20.0) > 1e-9:
        raise AssertionError(
            "independent storage flows were cross-credited: "
            f"expected 20.0, got {result.effective_regen_loss_kwh}; {result}"
        )


def test_explicit_terminal_target_preserves_device_imbalance() -> None:
    """An aggregate terminal target must not hide independent-device loss."""

    limits = {
        "A1": PowerArmElectricalLimit(
            max_traction_supply_kw=1e9,
            max_regen_absorption_kw=1e9,
            storage_available=True,
            storage_section_id="S1",
        ),
        "A2": PowerArmElectricalLimit(
            max_traction_supply_kw=1e9,
            max_regen_absorption_kw=1e9,
            storage_available=True,
            storage_section_id="S2",
        ),
    }
    # 初始 SOC 按 25/25 分配。S1 接收 25 kWh 再生能量，S2 从已有库存提供 25 kWh。
    # 汇总 SOC 仍等于显式目标值 50，但 50 kWh 有效损失确实存在：25 kWh 再生能量仍停留在储能中，
    # 另有 25 kWh 初始库存被消耗。
    result = EnergySettlementSystem(
        battery=_battery(round_trip_efficiency=1.0),
        settlement_time_step_s=10,
        initial_soc_kwh=50.0,
        target_final_soc_kwh=50.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=limits,
    ).settle(
        [
            {0: (-9000.0, 1.0, "A1", 10.0, "S1")},
            {10: (9000.0, 1.0, "A2", 10.0, "S2")},
        ]
    )
    if result.final_soc_by_storage_kwh != {"S1": 50.0, "S2": 0.0}:
        raise AssertionError(result)
    if abs(result.final_soc_kwh - result.target_final_soc_kwh) > 1e-9:
        raise AssertionError(result)
    if abs(result.effective_regen_loss_kwh - 50.0) > 1e-9:
        raise AssertionError(
            "aggregate target hid independent-device loss: "
            f"expected 50.0, got {result.effective_regen_loss_kwh}; {result}"
        )

    # 保留现有单设备终端目标语义；这些测试夹具用于区分目标偏差与转换/弃用损失。
    single_limit = {
        "A": PowerArmElectricalLimit(
            max_traction_supply_kw=1e9,
            max_regen_absorption_kw=1e9,
            storage_available=True,
            storage_section_id="S",
        )
    }
    no_flow = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        initial_soc_kwh=50.0,
        target_final_soc_kwh=100.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=single_limit,
    ).settle([{}])
    if abs(no_flow.effective_regen_loss_kwh - 50.0) > 1e-9:
        raise AssertionError(f"target shortfall semantics changed: {no_flow}")

    depleted = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        initial_soc_kwh=50.0,
        target_final_soc_kwh=100.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=single_limit,
    ).settle([{0: (18000.0, 1.0, "A", 10.0, "S")}])
    if abs(depleted.final_soc_kwh) > 1e-9 or abs(depleted.effective_regen_loss_kwh - 100.0) > 1e-9:
        raise AssertionError(f"target depletion semantics changed: {depleted}")

    parked = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        initial_soc_kwh=50.0,
        target_final_soc_kwh=50.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=single_limit,
    ).settle([{0: (-9000.0, 1.0, "A", 10.0, "S")}])
    if abs(parked.final_soc_kwh - 75.0) > 1e-9 or abs(parked.effective_regen_loss_kwh - 50.0) > 1e-9:
        raise AssertionError(f"target parked-charge semantics changed: {parked}")


def test_group_validation_is_atomic() -> None:
    """函数 test_group_validation_is_atomic：执行该模块中的相关处理逻辑。"""
    state = initialize_storage_settlement_state(
        ["S"], 100.0, 100.0, 100.0, 10.0, 1.0
    )
    limit = PowerArmElectricalLimit(storage_available=True, storage_section_id="S")
    for field_name in (
        "traction_kwh",
        "regen_kwh",
        "non_transfer_traction_kwh",
        "non_transfer_regen_kwh",
    ):
        values = {
            "traction_kwh": 0.0,
            "regen_kwh": 0.0,
            "non_transfer_traction_kwh": 0.0,
            "non_transfer_regen_kwh": 0.0,
        }
        values[field_name] = -0.1
        requests = [
            EnergyBucketRequest(0.0, 1.0, 0.0, 0.0, 0, 10, "S", limit),
            EnergyBucketRequest(
                **values,
                start_s=0,
                end_s=10,
                storage_section_id="S",
                limit=limit,
            ),
        ]
        before = dict(state.soc_by_storage_kwh)
        try:
            settle_energy_bucket_group(
                requests,
                allow_direct_use=False,
                allow_storage=True,
                storage_state=state,
            )
        except ValueError as exc:
            if field_name not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"negative {field_name} was accepted")
        if state.soc_by_storage_kwh != before:
            raise AssertionError("SOC changed before all requests were validated")

    invalid_limit = EnergyBucketRequest(
        0.0, 1.0, 0.0, 0.0, 0, 10, "S", object()  # type: ignore[arg-type]
    )
    try:
        settle_energy_bucket_group(
            [invalid_limit],
            allow_direct_use=False,
            allow_storage=True,
            storage_state=state,
        )
    except TypeError as exc:
        if "PowerArmElectricalLimit" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("invalid electrical-limit object was accepted")


def test_direct_use_crosses_storage_tags_on_same_arm() -> None:
    """函数 test_direct_use_crosses_storage_tags_on_same_arm：执行该模块中的相关处理逻辑。"""
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=10000.0,
        max_regen_absorption_kw=10000.0,
        storage_available=True,
        storage_section_id="S",
    )
    result = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=3600,
        allow_direct_use=True,
        allow_storage=False,
        power_arm_limits={"A1": limit},
    ).settle(
        [
            {0: (100.0, 1.0, "A1", 3600.0, "")},
            {0: (-100.0, 1.0, "A1", 3600.0, "S")},
        ]
    )
    if abs(result.direct_used_kwh - 100.0) > 1e-9:
        raise AssertionError(f"same-arm direct use was split by storage tags: {result}")
    if result.grid_kwh > 1e-9 or result.wasted_kwh > 1e-9:
        raise AssertionError(result)


def test_direct_use_respects_untagged_transfer_ratio() -> None:
    """An arm ID alone must not promote an out-of-zone sample to direct use."""

    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=10000.0,
        max_regen_absorption_kw=10000.0,
        storage_available=False,
    )
    result = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=True,
        allow_storage=False,
        power_arm_limits={"A1": limit},
    ).settle(
        [
            # 两个样本位于同一供电臂，但都在柔性区段之外。
            {0: (360.0, 0.0, "A1", 10.0, "")},
            {0: (-360.0, 0.0, "A1", 10.0, "")},
        ]
    )
    if result.direct_used_kwh != 0.0:
        raise AssertionError(
            "untagged zero-ratio samples were incorrectly credited as direct use: "
            f"{result}"
        )
    if abs(result.grid_kwh - 1.0) > 1e-9 or abs(result.wasted_kwh - 1.0) > 1e-9:
        raise AssertionError(f"out-of-zone energy was incorrectly recovered: {result}")


def test_direct_use_excludes_non_transfer_energy() -> None:
    """Direct use may only match transfer-eligible traction and regeneration."""

    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=10000.0,
        max_regen_absorption_kw=10000.0,
        storage_available=True,
        storage_section_id="S",
    )
    system = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=True,
        allow_storage=False,
        power_arm_limits={"A1": limit},
    )

    # 1 kWh 牵引能量明确不可转移，而 1 kWh 再生能量可以转移；
    # 两者共享供电臂，但不能进行直用配对。
    result = system.settle(
        [
            {0: (360.0, 0.0, "A1", 10.0, "S")},
            {0: (-360.0, 1.0, "A1", 10.0, "S")},
        ]
    )
    if result.direct_used_kwh != 0.0:
        raise AssertionError(
            "non-transfer traction was incorrectly credited as direct use: "
            f"{result}"
        )
    if abs(result.grid_kwh - 1.0) > 1e-9 or abs(result.wasted_kwh - 1.0) > 1e-9:
        raise AssertionError(
            "non-transfer traction/regeneration was not preserved after direct-use matching: "
            f"{result}"
        )

    # 反向情况同样成立：不可转移再生能量不能被可转移牵引消耗。
    result = system.settle(
        [
            {0: (360.0, 1.0, "A1", 10.0, "S")},
            {0: (-360.0, 0.0, "A1", 10.0, "S")},
        ]
    )
    if result.direct_used_kwh != 0.0:
        raise AssertionError(
            "non-transfer regeneration was incorrectly credited as direct use: "
            f"{result}"
        )
    if abs(result.grid_kwh - 1.0) > 1e-9 or abs(result.wasted_kwh - 1.0) > 1e-9:
        raise AssertionError(
            "non-transfer regeneration/traction was not preserved after direct-use matching: "
            f"{result}"
        )

    # 混合请求只能匹配其中符合条件的组件；不可转移的剩余部分仍必须体现在相应的电网/弃能总量中。
    result = system.settle(
        [
            {0: (720.0, 0.5, "A1", 10.0, "S")},
            {0: (-360.0, 1.0, "A1", 10.0, "S")},
        ]
    )
    if abs(result.direct_used_kwh - 1.0) > 1e-9:
        raise AssertionError(f"direct use consumed non-transfer traction: {result}")
    if abs(result.grid_kwh - 1.0) > 1e-9 or result.wasted_kwh > 1e-9:
        raise AssertionError(f"mixed transfer/non-transfer traction was mis-settled: {result}")

    result = system.settle(
        [
            {0: (360.0, 1.0, "A1", 10.0, "S")},
            {0: (-720.0, 0.5, "A1", 10.0, "S")},
        ]
    )
    if abs(result.direct_used_kwh - 1.0) > 1e-9:
        raise AssertionError(f"direct use consumed non-transfer regeneration: {result}")
    if result.grid_kwh > 1e-9 or abs(result.wasted_kwh - 1.0) > 1e-9:
        raise AssertionError(f"mixed transfer/non-transfer regeneration was mis-settled: {result}")


def test_unknown_power_arms_do_not_exchange_energy() -> None:
    """函数 test_unknown_power_arms_do_not_exchange_energy：执行该模块中的相关处理逻辑。"""
    result = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=True,
        allow_storage=False,
        power_arm_limits={},
    ).settle(
        [
            {0: (360.0, 1.0, "", 10.0, "")},
            {0: (-360.0, 1.0, "", 10.0, "")},
        ]
    )
    if result.direct_used_kwh != 0.0:
        raise AssertionError(
            f"unassigned power arms were treated as connected: {result}"
        )
    if abs(result.grid_kwh - 1.0) > 1e-9 or abs(result.wasted_kwh - 1.0) > 1e-9:
        raise AssertionError(result)


def test_non_transfer_regen_consumes_arm_absorption_room() -> None:
    """Storage must not bypass an arm limit already occupied by non-transfer regen."""

    state = initialize_storage_settlement_state(
        ["S"], 1000.0, 1000.0, 1000.0, 0.0, 1.0
    )
    limit = PowerArmElectricalLimit(
        max_regen_absorption_kw=100.0,
        storage_available=True,
        storage_section_id="S",
    )
    result = settle_energy_bucket_group(
        [
            EnergyBucketRequest(
                0.0, 100.0, 0.0, 100.0, 0, 3600, "S", limit, "A"
            )
        ],
        allow_direct_use=False,
        allow_storage=True,
        storage_state=state,
    )[0]
    if result.battery_charge_kwh != 0.0 or result.soc_after_kwh != 0.0:
        raise AssertionError(f"storage bypassed non-transfer regeneration: {result}")
    if abs(result.wasted_kwh - 200.0) > 1e-9:
        raise AssertionError(f"non-transfer regeneration was omitted: {result}")
    if abs(result.regen_absorption_excess_kwh - 100.0) > 1e-9:
        raise AssertionError(result)


def test_untagged_transfer_regen_consumes_arm_absorption_room() -> None:
    """Untagged transfer regeneration must not let storage bypass the arm limit."""

    state = initialize_storage_settlement_state(
        ["S"], 1000.0, 1000.0, 1000.0, 0.0, 1.0
    )
    limit = PowerArmElectricalLimit(
        max_regen_absorption_kw=100.0,
        storage_available=True,
        storage_section_id="S",
    )
    result = settle_energy_bucket_group(
        [
            # 该再生能量物理上位于供电臂内，但未连接到储能区段。
            EnergyBucketRequest(0.0, 100.0, 0.0, 0.0, 0, 3600, "", limit, "A"),
            # 带储能标签的再生能量共享同一个供电臂级限制。
            EnergyBucketRequest(0.0, 100.0, 0.0, 0.0, 0, 3600, "S", limit, "A"),
        ],
        allow_direct_use=False,
        allow_storage=True,
        storage_state=state,
    )
    if sum(item.battery_charge_kwh for item in result) != 0.0:
        raise AssertionError(
            "storage absorbed untagged transfer regeneration beyond the arm limit: "
            f"{result}"
        )
    if abs(sum(item.wasted_kwh for item in result) - 200.0) > 1e-9:
        raise AssertionError(f"regen waste was not preserved: {result}")
    if abs(sum(item.regen_absorption_excess_kwh for item in result) - 100.0) > 1e-9:
        raise AssertionError(f"arm absorption excess changed unexpectedly: {result}")


def test_non_transfer_energy_consumes_direct_use_arm_room() -> None:
    """Direct matching must reserve arm capacity occupied by non-transfer energy."""

    state = initialize_storage_settlement_state([], 1000.0, 1000.0, 1000.0, 0.0, 1.0)
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100.0,
        max_regen_absorption_kw=100.0,
    )
    result = settle_energy_bucket_group(
        [
            EnergyBucketRequest(100.0, 0.0, 100.0, 0.0, 0, 3600, "", limit, "A"),
            EnergyBucketRequest(0.0, 100.0, 0.0, 100.0, 0, 3600, "", limit, "A"),
        ],
        allow_direct_use=True,
        allow_storage=False,
        storage_state=state,
    )
    if any(item.direct_used_kwh != 0.0 for item in result):
        raise AssertionError(f"direct use bypassed non-transfer arm capacity: {result}")
    if abs(sum(item.traction_supply_excess_kwh for item in result) - 100.0) > 1e-9:
        raise AssertionError(result)
    if abs(sum(item.regen_absorption_excess_kwh for item in result) - 100.0) > 1e-9:
        raise AssertionError(result)


def test_direct_use_is_removed_before_arm_excess_check() -> None:
    """Matched direct energy must not be counted again as arm-limit excess."""

    state = initialize_storage_settlement_state([], 1000.0, 1000.0, 1000.0, 0.0, 1.0)
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100.0,
        max_regen_absorption_kw=100.0,
    )
    result = settle_energy_bucket_group(
        [
            EnergyBucketRequest(200.0, 0.0, 0.0, 0.0, 0, 3600, "", limit, "A"),
            EnergyBucketRequest(0.0, 200.0, 0.0, 0.0, 0, 3600, "", limit, "A"),
        ],
        allow_direct_use=True,
        allow_storage=False,
        storage_state=state,
    )
    if abs(sum(item.direct_used_kwh for item in result) - 100.0) > 1e-9:
        raise AssertionError(result)
    if any(
        abs(value) > 1e-9
        for item in result
        for value in (item.traction_supply_excess_kwh, item.regen_absorption_excess_kwh)
    ):
        raise AssertionError(f"direct-use residual was incorrectly marked as excess: {result}")


def test_power_arm_limit_is_not_duplicated_across_storage_sections() -> None:
    """函数 test_power_arm_limit_is_not_duplicated_across_storage_sections：执行该模块中的相关处理逻辑。"""
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=10000.0,
        max_regen_absorption_kw=100.0,
        storage_available=True,
        storage_section_id="S1;S2",
    )
    result = EnergySettlementSystem(
        battery=_battery(capacity_kwh=1000.0),
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": limit},
    ).settle(
        [
            {0: (-100.0, 1.0, "A1", 3600.0, "S1")},
            {0: (-100.0, 1.0, "A1", 3600.0, "S2")},
        ]
    )
    if abs(result.battery_charge_kwh - 100.0) > 1e-9:
        raise AssertionError(f"power-arm absorption limit was counted more than once: {result}")
    if abs(result.regen_absorption_excess_kwh - 100.0) > 1e-9:
        raise AssertionError(result)


def test_composite_power_arm_ids_are_order_invariant_for_grouping() -> None:
    """The same overlap written as A;B/B;A must share one physical bucket."""

    state = initialize_storage_settlement_state([], 1000.0, 1000.0, 1000.0, 0.0, 1.0)
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=1000.0,
        max_regen_absorption_kw=1000.0,
    )
    result = settle_energy_bucket_group(
        [
            EnergyBucketRequest(0.0, 100.0, 0.0, 0.0, 0, 3600, "", limit, "A;B"),
            EnergyBucketRequest(100.0, 0.0, 0.0, 0.0, 0, 3600, "", limit, "B;A"),
        ],
        allow_direct_use=True,
        allow_storage=False,
        storage_state=state,
    )
    if abs(sum(item.direct_used_kwh for item in result) - 100.0) > 1e-9:
        raise AssertionError(
            "order-variant composite IDs did not share direct-use matching: "
            f"{result}"
        )


def _record(time_s: int, ratio: float = 1.0) -> StepRecord:
    """函数 _record：执行该模块中的相关处理逻辑。"""
    return StepRecord(time_s, 0.0, 0.0, 0.0, 0.0, 100.0, ratio)


def test_build_power_series_rejects_overwrite_and_invalid_timing() -> None:
    """函数 test_build_power_series_rejects_overwrite_and_invalid_timing：执行该模块中的相关处理逻辑。"""
    invalid_cases = (
        ([_record(0), _record(0)], 0, "strictly increasing"),
        ([_record(10), _record(5)], 0, "strictly increasing"),
        ([_record(0)], -1, "depart_time_s"),
        ([_record(0)], 0.5, "depart_time_s"),
        ([_record(0, -0.1)], 0, "energy_transfer_ratio"),
        ([_record(0, 1.1)], 0, "energy_transfer_ratio"),
    )
    for records, depart_time_s, expected_text in invalid_cases:
        try:
            build_power_series(records, depart_time_s)  # type: ignore[arg-type]
        except ValueError as exc:
            if expected_text not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(
                f"invalid power-series input was accepted: {records!r}, {depart_time_s!r}"
            )


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_non_finite_power_raises()
    test_device_self_discharge_is_applied_per_elapsed_bucket()
    test_charge_limited_allocated_by_charge_capacity()
    test_multi_bin_energy_and_capacity()
    test_zero_storage_power_disables_charge_and_discharge()
    test_zero_efficiency_disables_initial_soc_discharge()
    test_storage_tag_cannot_override_unavailable_power_arm()
    test_storage_does_not_charge_and_discharge_in_same_bucket()
    test_simultaneous_group_requires_identical_positive_window()
    test_invalid_sample_time_rejected()
    test_effective_loss_rejects_invalid_numeric_inputs()
    test_effective_loss_counts_round_trip_efficiency_loss()
    test_effective_loss_preserves_conversion_loss_when_initial_soc_is_discharged()
    test_effective_loss_isolated_per_storage_device()
    test_explicit_terminal_target_preserves_device_imbalance()
    test_group_validation_is_atomic()
    test_direct_use_crosses_storage_tags_on_same_arm()
    test_direct_use_respects_untagged_transfer_ratio()
    test_direct_use_excludes_non_transfer_energy()
    test_unknown_power_arms_do_not_exchange_energy()
    test_non_transfer_regen_consumes_arm_absorption_room()
    test_untagged_transfer_regen_consumes_arm_absorption_room()
    test_non_transfer_energy_consumes_direct_use_arm_room()
    test_direct_use_is_removed_before_arm_excess_check()
    test_power_arm_limit_is_not_duplicated_across_storage_sections()
    test_composite_power_arm_ids_are_order_invariant_for_grouping()
    test_build_power_series_rejects_overwrite_and_invalid_timing()
    print("energy settlement correctness verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
