"""使用独立参考实现对随机合成案例执行差分测试。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import csv
import json
import math
import random
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import (
    EnergyBucketRequest,
    EnergySettlementSystem,
    initialize_storage_settlement_state,
    settle_energy_bucket_group,
)
from power_arm_electrical_limits import PowerArmElectricalLimit
from resource_constraints import (
    ResourceConfig,
    ResourceInterval,
    detect_resource_conflicts,
    resource_capacity_overlap_violation_s,
)
from timetable_optimizer import _dominates, pareto_rows
from train_simulator import BatteryStorageParameters


SCHEMA_VERSION = "1.0"
ABS_TOLERANCE = 1e-8
OBJECTIVE_TOLERANCE = 0.01
OBJECTIVE_FIELDS = (
    "effective_regen_loss_kwh_est",
    "grid_kwh_est",
    "total_adjustment_min",
)
ENERGY_FIELDS = (
    "direct_used_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
    "battery_charge_limited_kwh",
    "battery_discharge_limited_kwh",
    "wasted_kwh",
    "grid_kwh",
    "traction_supply_excess_kwh",
    "regen_absorption_excess_kwh",
)


def _alloc(total: float, capacities: Sequence[float]) -> list[float]:
    """独立比例分配参考，不调用生产实现。"""

    denominator = sum(max(0.0, value) for value in capacities)
    if total <= 0.0 or denominator <= 0.0:
        return [0.0] * len(capacities)
    return [total * max(0.0, value) / denominator for value in capacities]


def _reference_energy(case: Mapping[str, Any]) -> dict[str, float]:
    """按公开物理口径计算单供电臂、单储能设备的独立参考账本。"""

    requests = list(case["requests"])
    duration_h = (float(case["end_s"]) - float(case["start_s"])) / 3600.0
    traction = [float(item["traction_kwh"]) for item in requests]
    regen = [float(item["regen_kwh"]) for item in requests]
    non_traction = [float(item["non_transfer_traction_kwh"]) for item in requests]
    non_regen = [float(item["non_transfer_regen_kwh"]) for item in requests]
    tagged = [bool(item["storage_tagged"]) for item in requests]

    traction_room = float(case["traction_limit_kw"]) * duration_h
    regen_room = float(case["regen_limit_kw"]) * duration_h
    transfer_traction = sum(traction)
    transfer_regen = sum(regen)
    non_traction_total = sum(non_traction)
    non_regen_total = sum(non_regen)
    direct = 0.0
    if case["allow_direct_use"]:
        direct = min(
            transfer_traction,
            transfer_regen,
            max(0.0, traction_room - non_traction_total),
            max(0.0, regen_room - non_regen_total),
        )
    direct_traction = _alloc(direct, traction)
    direct_regen = _alloc(direct, regen)
    remaining_traction = [max(0.0, value - direct_traction[index]) for index, value in enumerate(traction)]
    remaining_regen = [max(0.0, value - direct_regen[index]) for index, value in enumerate(regen)]

    traction_excess = max(0.0, sum(remaining_traction) + non_traction_total - traction_room)
    regen_excess = max(0.0, sum(remaining_regen) + non_regen_total - regen_room)
    eligible_regen = [remaining_regen[index] if tagged[index] else 0.0 for index in range(len(requests))]
    untagged_regen = sum(
        remaining_regen[index] for index in range(len(requests)) if not tagged[index]
    )
    storage_input_room = min(
        sum(eligible_regen),
        max(0.0, regen_room - direct - non_regen_total - untagged_regen),
    )

    initial_soc = float(case["initial_soc_kwh"])
    efficiency = float(case["efficiency"])
    charge = 0.0
    charge_limited = 0.0
    if case["allow_storage"] and storage_input_room > 0.0 and efficiency > 0.0:
        capacity_input_room = max(0.0, (float(case["capacity_kwh"]) - initial_soc) / efficiency)
        desired_charge = min(storage_input_room, capacity_input_room)
        charge = min(desired_charge, float(case["charge_power_kw"]) * duration_h)
        charge_limited = max(0.0, desired_charge - charge)

    discharge = 0.0
    discharge_limited = 0.0
    tagged_traction = sum(
        remaining_traction[index] for index in range(len(requests)) if tagged[index]
    )
    if (
        case["allow_storage"]
        and tagged_traction > 0.0
        and charge <= 0.0
        and efficiency > 0.0
        and initial_soc > 0.0
    ):
        desired_discharge = min(tagged_traction, initial_soc)
        discharge = min(desired_discharge, float(case["discharge_power_kw"]) * duration_h)
        discharge_limited = max(0.0, desired_discharge - discharge)

    return {
        "direct_used_kwh": direct,
        "battery_charge_kwh": charge,
        "battery_discharge_kwh": discharge,
        "battery_charge_limited_kwh": charge_limited,
        "battery_discharge_limited_kwh": discharge_limited,
        "wasted_kwh": sum(remaining_regen) + non_regen_total - charge,
        "grid_kwh": sum(remaining_traction) + non_traction_total - discharge,
        "traction_supply_excess_kwh": traction_excess,
        "regen_absorption_excess_kwh": regen_excess,
        "final_soc_kwh": initial_soc + charge * efficiency - discharge,
    }


def _generate_energy_case(rng: random.Random, seed: int, case_index: int) -> dict[str, Any]:
    duration_s = rng.choice((1, 5, 10, 30, 60, 120))
    capacity = rng.uniform(0.0, 300.0)
    initial_soc = rng.uniform(0.0, capacity) if capacity > 0.0 else 0.0
    requests = []
    for _ in range(rng.randint(1, 5)):
        requests.append({
            "traction_kwh": rng.uniform(0.0, 120.0),
            "regen_kwh": rng.uniform(0.0, 120.0),
            "non_transfer_traction_kwh": rng.uniform(0.0, 40.0),
            "non_transfer_regen_kwh": rng.uniform(0.0, 40.0),
            "storage_tagged": rng.random() < 0.75,
        })
    return {
        "suite": "energy_bucket",
        "seed": seed,
        "case_index": case_index,
        "start_s": rng.randrange(0, 3600),
        "end_s": 0,
        "duration_s": duration_s,
        "capacity_kwh": capacity,
        "initial_soc_kwh": initial_soc,
        "efficiency": rng.uniform(0.55, 1.0),
        "charge_power_kw": rng.uniform(0.0, 12000.0),
        "discharge_power_kw": rng.uniform(0.0, 12000.0),
        "traction_limit_kw": rng.uniform(0.0, 12000.0),
        "regen_limit_kw": rng.uniform(0.0, 12000.0),
        "allow_direct_use": rng.choice((True, False)),
        "allow_storage": rng.choice((True, False)),
        "requests": requests,
    }


def _run_energy_case(case: dict[str, Any]) -> tuple[bool, float, dict[str, Any]]:
    case["end_s"] = int(case["start_s"]) + int(case["duration_s"])
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=case["traction_limit_kw"],
        max_regen_absorption_kw=case["regen_limit_kw"],
        storage_available=True,
        storage_section_id="S",
    )
    state = initialize_storage_settlement_state(
        ["S"],
        case["capacity_kwh"],
        case["charge_power_kw"],
        case["discharge_power_kw"],
        case["initial_soc_kwh"],
        case["efficiency"],
    )
    requests = [
        EnergyBucketRequest(
            traction_kwh=item["traction_kwh"],
            regen_kwh=item["regen_kwh"],
            non_transfer_traction_kwh=item["non_transfer_traction_kwh"],
            non_transfer_regen_kwh=item["non_transfer_regen_kwh"],
            start_s=case["start_s"],
            end_s=case["end_s"],
            storage_section_id="S" if item["storage_tagged"] else "",
            limit=limit,
            power_arm_id="A",
        )
        for item in case["requests"]
    ]
    actual_rows = settle_energy_bucket_group(
        requests,
        allow_direct_use=case["allow_direct_use"],
        allow_storage=case["allow_storage"],
        storage_state=state,
    )
    actual = {field: sum(float(getattr(row, field)) for row in actual_rows) for field in ENERGY_FIELDS}
    actual["final_soc_kwh"] = sum(state.soc_by_storage_kwh.values())
    expected = _reference_energy(case)
    errors = {field: abs(actual[field] - expected[field]) for field in expected}
    max_error = max(errors.values(), default=0.0)
    return max_error <= ABS_TOLERANCE, max_error, {
        "actual": actual,
        "expected": expected,
        "errors": errors,
    }


def _generate_time_slicing_case(
    rng: random.Random, seed: int, case_index: int
) -> dict[str, Any]:
    """生成包含跨桶、部分桶和多功率序列的随机输入。"""

    step_s = rng.choice((1, 5, 10, 30))
    series = []
    for _ in range(rng.randint(1, 4)):
        samples: dict[int, list[Any]] = {}
        for _sample_index in range(rng.randint(1, 8)):
            start_s = rng.randint(0, 180)
            while start_s in samples:
                start_s = rng.randint(0, 180)
            power_kw = rng.uniform(-12000.0, 12000.0)
            duration_s = rng.choice((0.5, 1.0, 3.0, 7.5, 10.0, 23.0, 45.0))
            samples[start_s] = [
                power_kw,
                rng.uniform(0.0, 1.0),
                "A",
                duration_s,
                "",
            ]
        series.append(samples)
    return {
        "suite": "energy_time_slicing",
        "seed": seed,
        "case_index": case_index,
        "settlement_step_s": step_s,
        "series": series,
    }


def _reference_time_slicing(case: Mapping[str, Any]) -> dict[str, Any]:
    step_s = int(case["settlement_step_s"])
    bins: dict[int, dict[str, float]] = {}
    total_gen = 0.0
    total_con = 0.0
    for series in case["series"]:
        for raw_start, sample in series.items():
            start_s = int(raw_start)
            power_kw = float(sample[0])
            duration_s = float(sample[3])
            energy_kwh = abs(power_kw) * duration_s / 3600.0
            if power_kw >= 0.0:
                total_con += energy_kwh
            else:
                total_gen += energy_kwh
            cursor = float(start_s)
            end_s = cursor + duration_s
            while cursor < end_s - 1e-12:
                bin_start = int(math.floor(cursor / step_s)) * step_s
                overlap_end = min(end_s, float(bin_start + step_s))
                overlap_kwh = abs(power_kw) * (overlap_end - cursor) / 3600.0
                bucket = bins.setdefault(bin_start, {"grid_kwh": 0.0, "wasted_kwh": 0.0})
                bucket["grid_kwh" if power_kw >= 0.0 else "wasted_kwh"] += overlap_kwh
                cursor = overlap_end
    return {
        "total_gen_kwh": total_gen,
        "total_con_kwh": total_con,
        "grid_kwh": total_con,
        "wasted_kwh": total_gen,
        "bins": bins,
    }


def _run_time_slicing_case(
    case: Mapping[str, Any]
) -> tuple[bool, float, dict[str, Any]]:
    step_s = int(case["settlement_step_s"])
    system = EnergySettlementSystem(
        BatteryStorageParameters(0.0, 1.0, 0.0, 1.0, 0.0, 0.0),
        settlement_time_step_s=step_s,
        allow_direct_use=False,
        allow_storage=False,
        power_arm_limits={
            "A": PowerArmElectricalLimit(
                max_traction_supply_kw=1e12,
                max_regen_absorption_kw=1e12,
            )
        },
    )
    actual_result = system.settle(
        [
            {int(start): tuple(sample) for start, sample in series.items()}
            for series in case["series"]
        ]
    )
    expected = _reference_time_slicing(case)
    actual = {
        "total_gen_kwh": actual_result.total_gen_kwh,
        "total_con_kwh": actual_result.total_con_kwh,
        "grid_kwh": actual_result.grid_kwh,
        "wasted_kwh": actual_result.wasted_kwh,
    }
    errors = {
        field: abs(actual[field] - float(expected[field]))
        for field in ("total_gen_kwh", "total_con_kwh", "grid_kwh", "wasted_kwh")
    }
    actual_bins = {
        int(time_s): {
            "grid_kwh": float(actual_result.grid_kW[index]) * step_s / 3600.0,
            "wasted_kwh": float(actual_result.wasted_kW[index]) * step_s / 3600.0,
        }
        for index, time_s in enumerate(actual_result.timeline_s)
    }
    bin_keys = set(actual_bins) | set(expected["bins"])
    for bin_start in bin_keys:
        for metric in ("grid_kwh", "wasted_kwh"):
            errors[f"bin:{bin_start}:{metric}"] = abs(
                actual_bins.get(bin_start, {}).get(metric, 0.0)
                - expected["bins"].get(bin_start, {}).get(metric, 0.0)
            )
    max_error = max(errors.values(), default=0.0)
    return max_error <= ABS_TOLERANCE, max_error, {
        "actual": actual,
        "expected_totals": {key: value for key, value in expected.items() if key != "bins"},
        "errors": errors,
        "actual_bin_count": len(actual_bins),
        "expected_bin_count": len(expected["bins"]),
    }


def _generate_resource_case(rng: random.Random, seed: int, case_index: int) -> dict[str, Any]:
    intervals = []
    for resource_index in range(rng.randint(1, 4)):
        resource_id = f"R{resource_index}"
        resource_type = rng.choice(("section", "station_track", "station_throat"))
        for interval_index in range(rng.randint(2, 10)):
            start = rng.randint(0, 120)
            intervals.append({
                "resource_id": resource_id,
                "resource_name": resource_id,
                "resource_type": resource_type,
                "capacity": 1,
                "train_id": f"T{resource_index}_{interval_index}",
                "train_type": rng.choice(("Heavy", "Empty")),
                "direction": rng.choice(("forward", "reverse")),
                "start_time_s": start,
                "end_time_s": start + rng.randint(1, 40),
                "start_km": float(resource_index * 10),
                "end_km": float(resource_index * 10 + 5),
                "detail": "random differential case",
            })
    return {
        "suite": "resource_overlap",
        "seed": seed,
        "case_index": case_index,
        "min_overlap_s": rng.choice((0, 1, 2, 5)),
        "intervals": intervals,
    }


def _reference_resource(case: Mapping[str, Any]) -> dict[str, Any]:
    min_overlap = int(case["min_overlap_s"])
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for interval in case["intervals"]:
        grouped.setdefault(str(interval["resource_id"]), []).append(interval)
    conflict_keys = set()
    violation = 0.0
    for resource_id, items in grouped.items():
        for left_index, left in enumerate(items):
            for right in items[left_index + 1 :]:
                start = max(int(left["start_time_s"]), int(right["start_time_s"]))
                end = min(int(left["end_time_s"]), int(right["end_time_s"]))
                if end - start > min_overlap:
                    conflict_keys.add((resource_id, tuple(sorted((left["train_id"], right["train_id"]))), start, end))
        start_bound = min(int(item["start_time_s"]) for item in items)
        end_bound = max(int(item["end_time_s"]) for item in items)
        excess_by_second = []
        for second in range(start_bound, end_bound):
            occupancy = sum(
                int(item["start_time_s"]) <= second < int(item["end_time_s"])
                for item in items
            )
            excess_by_second.append(max(0, occupancy - 1))
        index = 0
        while index < len(excess_by_second):
            if excess_by_second[index] <= 0:
                index += 1
                continue
            episode_start = index
            episode_total = 0
            while index < len(excess_by_second) and excess_by_second[index] > 0:
                episode_total += excess_by_second[index]
                index += 1
            if index - episode_start > min_overlap:
                violation += episode_total
    return {"conflict_keys": conflict_keys, "violation_s": float(violation)}


def _run_resource_case(case: Mapping[str, Any]) -> tuple[bool, float, dict[str, Any]]:
    intervals = [ResourceInterval(**item) for item in case["intervals"]]
    config = ResourceConfig(min_overlap_s=case["min_overlap_s"], conflict_limit=100000)
    actual_conflicts = detect_resource_conflicts(intervals, config)
    actual_keys = {
        (
            item.resource_id,
            tuple(sorted((item.train_a, item.train_b))),
            int(item.overlap_start_s),
            int(item.overlap_end_s),
        )
        for item in actual_conflicts
    }
    actual_violation = resource_capacity_overlap_violation_s(intervals, config)
    expected = _reference_resource(case)
    violation_error = abs(actual_violation - expected["violation_s"])
    missing = sorted(expected["conflict_keys"] - actual_keys)
    extra = sorted(actual_keys - expected["conflict_keys"])
    passed = not missing and not extra and violation_error <= ABS_TOLERANCE
    return passed, violation_error, {
        "actual_conflict_count": len(actual_keys),
        "expected_conflict_count": len(expected["conflict_keys"]),
        "actual_violation_s": actual_violation,
        "expected_violation_s": expected["violation_s"],
        "missing_conflicts": missing[:10],
        "extra_conflicts": extra[:10],
    }


def _quantized_objectives(row: Mapping[str, Any]) -> tuple[int, int, int]:
    return tuple(int(round(float(row[field]) / OBJECTIVE_TOLERANCE)) for field in OBJECTIVE_FIELDS)


def _reference_dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_feasible = float(left["constraint_violation"]) <= 1e-9
    right_feasible = float(right["constraint_violation"]) <= 1e-9
    if left_feasible != right_feasible:
        return left_feasible
    if not left_feasible:
        return float(left["constraint_violation"]) < float(right["constraint_violation"])
    left_values = _quantized_objectives(left)
    right_values = _quantized_objectives(right)
    return all(a <= b for a, b in zip(left_values, right_values)) and any(
        a < b for a, b in zip(left_values, right_values)
    )


def _reference_pareto_ids(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    feasible = [row for row in rows if float(row["constraint_violation"]) <= 1e-9]
    front = [
        row for row in feasible
        if not any(_reference_dominates(other, row) for other in feasible if other is not row)
    ]
    selected = []
    seen = set()
    for row in sorted(front, key=lambda item: (_quantized_objectives(item), str(item["candidate_id"]))):
        key = _quantized_objectives(row)
        if key in seen:
            continue
        seen.add(key)
        selected.append(str(row["candidate_id"]))
    return sorted(selected)


def _generate_pareto_case(rng: random.Random, seed: int, case_index: int) -> dict[str, Any]:
    rows = []
    for candidate_index in range(rng.randint(4, 24)):
        if rows and rng.random() < 0.18:
            source = rng.choice(rows)
            loss = source["effective_regen_loss_kwh_est"]
            grid = source["grid_kwh_est"]
            adjustment = source["total_adjustment_min"]
        else:
            loss = rng.uniform(0.0, 5000.0)
            grid = rng.uniform(0.0, 40000.0)
            adjustment = rng.uniform(0.0, 120.0)
        rows.append({
            "candidate_id": f"C{candidate_index:03d}",
            "scenario_id": "storage_no_direct",
            "effective_regen_loss_kwh_est": loss,
            "grid_kwh_est": grid,
            "total_adjustment_min": adjustment,
            "constraint_violation": 0.0 if rng.random() < 0.8 else rng.uniform(0.001, 10.0),
        })
    return {
        "suite": "pareto_front",
        "seed": seed,
        "case_index": case_index,
        "rows": rows,
    }


def _run_pareto_case(case: Mapping[str, Any]) -> tuple[bool, float, dict[str, Any]]:
    rows = list(case["rows"])
    expected_ids = _reference_pareto_ids(rows)
    actual_ids = sorted(str(row["candidate_id"]) for row in pareto_rows(rows))
    pair_mismatches = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1 :]:
            for first, second in ((left, right), (right, left)):
                if _dominates(first, second) != _reference_dominates(first, second):
                    pair_mismatches.append((first["candidate_id"], second["candidate_id"]))
    passed = actual_ids == expected_ids and not pair_mismatches
    return passed, float(len(pair_mismatches) + len(set(actual_ids) ^ set(expected_ids))), {
        "actual_ids": actual_ids,
        "expected_ids": expected_ids,
        "pair_mismatches": pair_mismatches[:10],
    }


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def run_differential_tests(
    output_dir: Path,
    *,
    seeds: Sequence[int],
    energy_cases: int,
    time_slicing_cases: int,
    resource_cases: int,
    pareto_cases: int,
) -> dict[str, Any]:
    """执行全部随机差分套件并写出可复现证据。"""

    if not seeds or any(isinstance(seed, bool) for seed in seeds):
        raise ValueError("seeds必须包含至少一个整数种子")
    for name, value in (
        ("energy_cases", energy_cases),
        ("time_slicing_cases", time_slicing_cases),
        ("resource_cases", resource_cases),
        ("pareto_cases", pareto_cases),
    ):
        if isinstance(value, bool) or int(value) != value or value <= 0:
            raise ValueError(f"{name}必须为正整数")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    generated_hashes: list[str] = []
    suites = (
        ("energy_bucket", energy_cases, _generate_energy_case, _run_energy_case),
        (
            "energy_time_slicing",
            time_slicing_cases,
            _generate_time_slicing_case,
            _run_time_slicing_case,
        ),
        ("resource_overlap", resource_cases, _generate_resource_case, _run_resource_case),
        ("pareto_front", pareto_cases, _generate_pareto_case, _run_pareto_case),
    )
    for seed in seeds:
        rng = random.Random(int(seed))
        for suite, count, generator, runner in suites:
            for case_index in range(int(count)):
                case = generator(rng, int(seed), case_index)
                case_hash = _canonical_hash(case)
                generated_hashes.append(case_hash)
                try:
                    passed, max_error, details = runner(case)
                    error = ""
                except Exception as exc:
                    passed, max_error, details = False, math.inf, {}
                    error = f"{type(exc).__name__}: {exc}"
                stored_error = max_error if math.isfinite(max_error) else "non_finite"
                rows.append({
                    "suite": suite,
                    "seed": int(seed),
                    "case_index": case_index,
                    "case_sha256": case_hash,
                    "passed": passed,
                    "max_absolute_error": stored_error,
                    "error": error,
                })
                if not passed:
                    failures.append({
                        "suite": suite,
                        "seed": int(seed),
                        "case_index": case_index,
                        "case_sha256": case_hash,
                        "error": error,
                        "max_absolute_error": None if not math.isfinite(max_error) else max_error,
                        "input": case,
                        "details": details,
                    })
    suite_summaries = {}
    for suite, _count, _generator, _runner in suites:
        suite_rows = [row for row in rows if row["suite"] == suite]
        suite_summaries[suite] = {
            "case_count": len(suite_rows),
            "passed_count": sum(bool(row["passed"]) for row in suite_rows),
            "failed_count": sum(not bool(row["passed"]) for row in suite_rows),
            "max_absolute_error": max(
                (
                    float(row["max_absolute_error"])
                    for row in suite_rows
                    if row["max_absolute_error"] != "non_finite"
                    and math.isfinite(float(row["max_absolute_error"]))
                ),
                default=0.0,
            ),
        }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "passed": not failures,
        "seeds": [int(seed) for seed in seeds],
        "case_configuration_per_seed": {
            "energy_bucket": int(energy_cases),
            "energy_time_slicing": int(time_slicing_cases),
            "resource_overlap": int(resource_cases),
            "pareto_front": int(pareto_cases),
        },
        "total_case_count": len(rows),
        "passed_count": sum(bool(row["passed"]) for row in rows),
        "failed_count": len(failures),
        "case_set_sha256": _canonical_hash(generated_hashes),
        "absolute_tolerance": ABS_TOLERANCE,
        "suites": suite_summaries,
        "outputs": {
            "report": "RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md",
            "case_results": "random_synthetic_differential_cases.csv",
            "failure_replay": "random_synthetic_differential_failures.json",
            "summary": "random_synthetic_differential_summary.json",
        },
    }
    with (output_dir / "random_synthetic_differential_cases.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "random_synthetic_differential_failures.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "failures": failures}, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "random_synthetic_differential_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 随机合成案例差分测试",
        "",
        f"结论：`{'PASS' if summary['passed'] else 'FAIL'}`。共执行 {summary['total_case_count']} 个案例，失败 {summary['failed_count']} 个。",
        "",
        f"固定种子：`{', '.join(str(seed) for seed in seeds)}`；案例集合 SHA-256：`{summary['case_set_sha256']}`。",
        "",
        "| 套件 | 案例 | 通过 | 失败 | 最大绝对误差 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for suite, item in suite_summaries.items():
        lines.append(
            f"| `{suite}` | {item['case_count']} | {item['passed_count']} | {item['failed_count']} | {item['max_absolute_error']:.3g} |"
        )
    lines.extend([
        "",
        "## 差分两端",
        "",
        "- 能量结算：生产 `settle_energy_bucket_group` 对比独立单供电臂/单设备账本参考模型，覆盖直用开关、储能开关、部分可转移能量、无储能标签、功率/容量/SOC和供电臂限值。",
        "- 时间分桶：生产 `EnergySettlementSystem.settle` 对比独立区间切片积分，覆盖多序列、跨桶和部分时间桶。",
        "- 资源约束：生产冲突检测与超容量积分对比逐对重叠和逐秒占用枚举参考模型。",
        "- Pareto：生产支配与前沿去重对比独立量化目标穷举参考模型，覆盖可行/不可行候选和重复目标。",
        "",
        "失败时可使用 `random_synthetic_differential_failures.json` 中的种子、案例序号、完整输入和差值进行确定性回放。测试数据均为合成值，不构成正式工程结论。",
    ])
    (output_dir / "RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/random_synthetic_differential"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[20260909, 20260910, 20260911])
    parser.add_argument("--energy-cases", type=int, default=500)
    parser.add_argument("--time-slicing-cases", type=int, default=300)
    parser.add_argument("--resource-cases", type=int, default=500)
    parser.add_argument("--pareto-cases", type=int, default=300)
    args = parser.parse_args(argv)
    summary = run_differential_tests(
        args.output_dir,
        seeds=args.seeds,
        energy_cases=args.energy_cases,
        time_slicing_cases=args.time_slicing_cases,
        resource_cases=args.resource_cases,
        pareto_cases=args.pareto_cases,
    )
    print(json.dumps({
        "passed": summary["passed"],
        "total_case_count": summary["total_case_count"],
        "failed_count": summary["failed_count"],
        "report": str(args.output_dir / "RANDOM_SYNTHETIC_DIFFERENTIAL_REPORT.md"),
    }, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
