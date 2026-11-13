"""参数地图扫描工具的回归测试。

这个工具替人做的判断是「折旧维可以解析外推」——如果这条线性化不成立，
整张图就是错的，而且错得很隐蔽（数字仍然平滑、仍然单调）。
所以这里先把它锁死：

1. **解析重算必须逐位复现仿真记录值**：拿一次真实规划输出，
   对每个候选方案用「固定项 + 吞吐 × 折旧」重算盈亏电价，
   必须与 CSV 里记录的 `break_even_grid_price_cny_per_kwh` 完全一致；
2. **折旧是线性的**：斜率必须等于吞吐除以减购电量，与读数无关；
3. **容量上限改写要落到三张表**（技术族、候选站、站点技术选项），
   漏一张就会让上限被静默忽略，扫描退化成同一个点；
4. **往返效率按对称拆分**：两侧乘积必须等于目标值；
5. **合并逻辑不能跨批次覆盖**：两批不同容量上限的结果必须同时保留。

依赖真实输出的用例在文件缺失时跳过（发布包不含 outputs/）。
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scan_storage_parameter_map import (  # noqa: E402
    BASE_DEGRADATION,
    _merge_previous,
    break_even_of,
    build_input_variant,
    evaluate_cell,
    load_cell,
)

PLAN_DIR = ROOT / "outputs" / "timetable_measured" / "plan"
INPUT_DIR = ROOT / "outputs" / "timetable_measured" / "inputs"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_analytic_reconstruction() -> None:
    """核心断言：线性化必须与仿真记录逐位一致。"""

    if not (PLAN_DIR / "storage_plan_candidates.csv").exists() or not (
        INPUT_DIR / "storage_planning_scenarios.json"
    ).exists():
        print("[SKIP] 解析重算（缺 outputs/timetable_measured）")
        return

    cell = load_cell(PLAN_DIR, INPUT_DIR)
    check("候选方案被正确筛出", len(cell["plans"]) > 0, f"实际 {len(cell['plans'])}")
    check(
        "基线非电网成本为正（含弃能罚款与需量电费）",
        cell["baseline_non_grid_cny"] > 0,
        f"实际 {cell['baseline_non_grid_cny']:,.0f}",
    )

    worst = 0.0
    for plan in cell["plans"]:
        recomputed = break_even_of(plan, BASE_DEGRADATION, cell["baseline_non_grid_cny"])
        worst = max(worst, abs(recomputed - plan["break_even_at_base"]))
    check("解析重算与记录值逐位一致（误差 < 1e-9）", worst < 1e-9, f"最大偏差 {worst:.3e}")


def test_linear_in_degradation() -> None:
    if not (PLAN_DIR / "storage_plan_candidates.csv").exists():
        print("[SKIP] 折旧线性性（缺 outputs/timetable_measured）")
        return
    cell = load_cell(PLAN_DIR, INPUT_DIR)
    plan = cell["plans"][0]
    baseline = cell["baseline_non_grid_cny"]
    low = break_even_of(plan, 0.0, baseline)
    high = break_even_of(plan, 1.0, baseline)
    expected_slope = plan["throughput_kwh"] / plan["grid_reduction_kwh"]
    check(
        "折旧 0 → 1 元的斜率 = 吞吐 / 减购电量",
        abs((high - low) - expected_slope) < 1e-9,
        f"实际 {high - low:.6f} vs 期望 {expected_slope:.6f}",
    )
    check("吞吐量为正（否则折旧维无意义）", plan["throughput_kwh"] > 0)


def test_viable_flag() -> None:
    if not (PLAN_DIR / "storage_plan_candidates.csv").exists():
        print("[SKIP] 成立判定（缺 outputs/timetable_measured）")
        return
    cell = load_cell(PLAN_DIR, INPUT_DIR)
    price = cell["grid_price_cny_per_kwh"]
    grid = evaluate_cell(cell, [0.0, 0.2, 0.326, 0.5, 0.8], price)
    check("每个折旧档都给出方案", len(grid) == 5, f"实际 {len(grid)}")
    consistent = all(
        item["viable"] == (item["break_even_cny_per_kwh"] < price) for item in grid
    )
    check("viable 标志与盈亏电价判定一致", consistent)
    check(
        "折旧越高盈亏电价越高（单调）",
        all(grid[i]["break_even_cny_per_kwh"] <= grid[i + 1]["break_even_cny_per_kwh"] for i in range(4)),
    )
    check(
        "年节约 = (电价 − 盈亏电价) × 减购电量",
        all(
            abs(item["annual_saving_cny"] - (price - item["break_even_cny_per_kwh"]) * item["grid_reduction_kwh"])
            < 1e-3
            for item in grid
        ),
    )


def test_input_variant(tmp_root: Path) -> None:
    if not (INPUT_DIR / "storage_technologies.csv").exists():
        print("[SKIP] 输入变体（缺 outputs/timetable_measured/inputs）")
        return
    target = tmp_root / f"variant_{int(3000)}"
    build_input_variant(INPUT_DIR, target, 3000.0, 0.93)
    tech = _read_csv(target / "storage_technologies.csv")[0]
    round_trip = float(tech["charge_efficiency"]) * float(tech["discharge_efficiency"])
    check("往返效率按对称拆分还原为目标值", abs(round_trip - 0.93) < 1e-9, f"实际 {round_trip:.9f}")
    check("折旧单价未被改写（解析基准必须保持）", abs(float(tech["throughput_degradation_cost_per_kwh"]) - BASE_DEGRADATION) < 1e-12)
    check("技术族容量上限已改写", abs(float(tech["max_capacity_kwh"]) - 3000.0) < 1e-9)
    for name in ("storage_candidate_sites.csv", "storage_site_technology_options.csv"):
        rows = _read_csv(target / name)
        check(f"{name} 容量上限已改写", all(abs(float(row["max_capacity_kwh"]) - 3000.0) < 1e-9 for row in rows))


def test_merge_keeps_batches(tmp_root: Path) -> None:
    out = tmp_root / "merge"
    out.mkdir(parents=True, exist_ok=True)
    fields = [
        "capacity_cap_kwh",
        "round_trip_efficiency",
        "degradation_cny_per_kwh",
        "break_even_cny_per_kwh",
    ]
    (out / "parameter_map.json").write_text('{"cells": []}', encoding="utf-8")
    with (out / "parameter_map.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "capacity_cap_kwh": 290,
                "round_trip_efficiency": 0.9,
                "degradation_cny_per_kwh": 0.326,
                "break_even_cny_per_kwh": 3.54,
            }
        )
    records = [
        {
            "capacity_cap_kwh": 3000.0,
            "round_trip_efficiency": 0.9,
            "degradation_cny_per_kwh": 0.326,
            "break_even_cny_per_kwh": 1.15,
        }
    ]
    merged_records, _ = _merge_previous(out, records, [{"capacity_cap_kwh": 3000.0, "round_trip_efficiency": 0.9}])
    check("合并后两批结果同时保留", len(merged_records) == 2, f"实际 {len(merged_records)}")
    caps = {float(row["capacity_cap_kwh"]) for row in merged_records}
    check("合并后容量档齐全", caps == {290.0, 3000.0}, f"实际 {caps}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        test_analytic_reconstruction()
        test_linear_in_degradation()
        test_viable_flag()
        test_input_variant(tmp_root)
        test_merge_keeps_batches(tmp_root)

    print()
    if failures:
        print(f"{len(failures)} 项失败： {failures}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
