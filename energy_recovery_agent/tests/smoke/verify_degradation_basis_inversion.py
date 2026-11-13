"""折旧口径反演的回归测试。

这个工具的全部结论都建立在一条假设上：**工具重算的年化投资与规划器记录的完全一致**。
如果这条不成立，后面「重复计了两遍」的判断就只是猜。所以这里把它锁死：

1. `annualize(mode="replace")` 必须逐位复现 `annualized_capex_cny`（22 个候选方案）；
2. `mode="single"` 必须严格小于 `mode="replace"`（只要发生过重置）；
3. 设备磨损口径必须显著低于 0.326——这正是「重复计」的量化依据；
4. 反解的隐含循环寿命必须低于技术表给的 6,000 次；
5. 口径 B 与 A 的差必须恰好等于 `0.326 × 吞吐 ÷ 减购电量`（两个口径只差这一项）；
6. 容量、功率、站点固定三块加起来必须等于记录的 capex（造价拆分不能漏项）。

依赖真实输出的用例在文件缺失时跳过（发布包不含 outputs/）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.invert_storage_degradation_basis import (  # noqa: E402
    BASE_DEGRADATION,
    _crf,
    annualize,
    capex_breakdown,
    embedded_wear,
    evaluate,
    implied_wear,
    load_run,
    reannualize_plan,
    reverse_solve,
)

RUN_DIR = ROOT / "outputs" / "storage_parameter_map" / "runs" / "cap3000_eta0.90"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def _skip(label: str) -> bool:
    if not (RUN_DIR / "plan" / "storage_plan_candidates.csv").exists():
        print(f"[SKIP] {label}（缺 outputs/storage_parameter_map）")
        return True
    return False


def test_annualization_reproduces() -> None:
    """核心断言：两种口径重算，replace 必须与规划器一致。"""

    if _skip("年化重算逐位一致"):
        return
    run = load_run(RUN_DIR)
    worst = 0.0
    for plan in run["plans"]:
        worst = max(worst, abs(reannualize_plan(plan, run, "replace") - plan["annualized_capex_cny"]))
    check("replace 口径重算与记录一致（误差 < 1e-6 元）", worst < 1e-6, f"最大偏差 {worst:.6e}")

    single_less = all(
        reannualize_plan(plan, run, "single") < plan["annualized_capex_cny"] - 1.0 for plan in run["plans"]
    )
    check("single 口径（不重置）显著低于 replace", single_less)


def test_capex_breakdown() -> None:
    if _skip("造价拆分"):
        return
    run = load_run(RUN_DIR)
    worst = 0.0
    for plan in run["plans"]:
        worst = max(worst, abs(plan["capex"]["total_cny"] - sum(
            float(item["capex_cny"]) for item in plan["devices"]
        )))
    check("四块造价之和等于设备表 capex", worst < 1e-6, f"最大偏差 {worst:.6e}")


def test_wear_below_documented() -> None:
    if _skip("磨损口径低于 0.326"):
        return
    run = load_run(RUN_DIR)
    plan = run["plans"][0]
    wear = implied_wear(plan, run)
    documented = float(run["tech"]["throughput_degradation_cost_per_kwh"])
    check("设备磨损口径低于甲方文档值", wear["wear_per_throughput_cny_per_kwh"] < documented,
          f"{wear['wear_per_throughput_cny_per_kwh']:.4f} vs {documented}")
    check("纯容量磨损口径低于设备口径",
          wear["capacity_wear_only_cny_per_kwh"] < wear["wear_per_throughput_cny_per_kwh"])

    embed = embedded_wear(plan, run, plan["annualized_capex_cny"])
    check("年化里已经含了正的每吞吐成本", embed["embedded_cny_per_kwh"] > 0.0)
    check("年化已含 + 显式折旧 > 单算磨损（重复计成立）",
          embed["embedded_cny_per_kwh"] + BASE_DEGRADATION > wear["wear_per_throughput_cny_per_kwh"])


def test_reverse_solve() -> None:
    if _skip("反解隐含寿命"):
        return
    run = load_run(RUN_DIR)
    plan = run["plans"][0]
    values = reverse_solve(plan, run, BASE_DEGRADATION)
    cycle_life = float(run["tech"]["cycle_life"])
    check("容量口径隐含循环寿命低于技术表",
          values["implied_cycles_capacity_only"] < cycle_life,
          f"{values['implied_cycles_capacity_only']:.0f} vs {cycle_life:.0f}")
    check("全设备口径隐含循环寿命低于技术表",
          values["implied_cycles_all_equipment"] < cycle_life,
          f"{values['implied_cycles_all_equipment']:.0f} vs {cycle_life:.0f}")
    check("日历口径隐含年吞吐低于实际吞吐",
          values["implied_annual_throughput_kwh"] < plan["throughput_kwh"])


def test_conventions_differ_by_one_term() -> None:
    if _skip("口径 A/B 只差折旧一项"):
        return
    run = load_run(RUN_DIR)
    annualized = {
        "replace": {plan["plan_id"]: reannualize_plan(plan, run, "replace") for plan in run["plans"]},
        "single": {plan["plan_id"]: reannualize_plan(plan, run, "single") for plan in run["plans"]},
    }
    records = {item["convention"][0]: item for item in evaluate(run, annualized)}
    check("四种口径都给出了结果", set(records) == {"A", "B", "C", "D"}, f"实际 {sorted(records)}")

    a, b = records["A"], records["B"]
    expected_gap = BASE_DEGRADATION * a["throughput_kwh"] / a["reduction_kwh"]
    check("A 与 B 的盈亏电价之差 = 0.326 × 吞吐 ÷ 减购电",
          abs((a["break_even_cny_per_kwh"] - b["break_even_cny_per_kwh"]) - expected_gap) < 1e-6,
          f"实际 {a['break_even_cny_per_kwh'] - b['break_even_cny_per_kwh']:.6f} vs {expected_gap:.6f}")
    check("B 的盈亏电价低于 A", b["break_even_cny_per_kwh"] < a["break_even_cny_per_kwh"])
    for key in ("A", "B", "C", "D"):
        check(f"口径 {key} 的 viable 标志与判定一致",
              records[key]["viable"] == (records[key]["break_even_cny_per_kwh"] < run["grid_price"]))


def test_crf() -> None:
    check("CRF(12, 6%) 约 0.1193", abs(_crf(12, 0.06) - 0.119277) < 1e-5, f"实际 {_crf(12, 0.06):.6f}")
    check("CRF 随折现率单调增", _crf(12, 0.06) < _crf(12, 0.10))
    # CRF 对应「年金在期末」（t=1..12），不是期初；用错范围会差一个 1.06 倍。
    check("年化系数 × 期末年金现值 = 1", abs(_crf(12, 0.06) * sum(1 / 1.06**t for t in range(1, 13)) - 1.0) < 1e-9)


def test_annualize_shapes() -> None:
    tech = {"calendar_life_years": "12", "cycle_life": "6000"}
    # 年循环 0（不循环）→ 只受日历寿命限制，等价于单次投资
    replace_none = annualize(0.0, 1_000_000.0, 0.0, tech, 12, 0.06, "replace")
    single = annualize(0.0, 1_000_000.0, 0.0, tech, 12, 0.06, "single")
    check("零循环时两种口径退化为同一值", abs(replace_none - single) < 1e-6,
          f"{replace_none:.2f} vs {single:.2f}")
    # 高循环 → 寿命远短于日历 → 年化更高
    heavy = annualize(0.0, 1_000_000.0, 5000.0, tech, 12, 0.06, "replace")
    check("高循环推高年化（重置变频繁）", heavy > single * 2, f"{heavy:.0f} vs {single:.0f}")


def main() -> int:
    test_crf()
    test_annualize_shapes()
    test_annualization_reproduces()
    test_capex_breakdown()
    test_wear_below_documented()
    test_reverse_solve()
    test_conventions_differ_by_one_term()

    print()
    if failures:
        print(f"{len(failures)} 项失败： {failures}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
