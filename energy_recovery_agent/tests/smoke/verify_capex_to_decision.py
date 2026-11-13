"""造价 → 决策 一维扫描的回归测试。

这个扫描的全部结论建立在「造价只进成本、不进调度」这一条上。所以测试要锁住：

1. **k=1 必须复现仿真记录**：造价水平 100% 时算出的盈亏电价，
   必须等于规划器写在候选表里的最小值（1.1459），否则缩放口径就错了；
2. **线性性**：固定方案下，盈亏电价对造价水平是一次函数，
   取三点必须共线；
3. **单调性**：造价越便宜，盈亏电价不能上升；
4. **门槛自洽**：二分出来的门槛点上，刚好跨过现价；门槛下方成立、上方不成立；
5. **顺序合理**：A（重置+0.326）比 C（单次+0.326）更贵，因此 A 的门槛必须更低（要降更多）；
   B（折旧 0）在现价就该成立。

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
    load_run,
    reannualize_plan,
)
from tools.scan_capex_to_decision import (  # noqa: E402
    _break_even,
    find_threshold,
    scan_level,
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


def _annualized(run):
    return {
        mode: {plan["plan_id"]: reannualize_plan(plan, run, mode) for plan in run["plans"]}
        for mode in ("replace", "single")
    }


def test_reproduces_record_at_full_price() -> None:
    if _skip("k=1 复现记录"):
        return
    run = load_run(RUN_DIR)
    annualized = _annualized(run)
    at_full = scan_level(run, annualized, "replace", BASE_DEGRADATION, 1.0)
    check("k=1 的 A 口径盈亏电价约 1.146", abs(at_full["break_even_cny_per_kwh"] - 1.145946) < 1e-4,
          f"实际 {at_full['break_even_cny_per_kwh']:.6f}")


def test_linear_in_capex_level() -> None:
    if _skip("造价线性性"):
        return
    run = load_run(RUN_DIR)
    annualized = _annualized(run)
    plan = run["plans"][0]
    a = annualized["replace"][plan["plan_id"]]
    points = [
        _break_even(plan, run, a, level, BASE_DEGRADATION) for level in (0.0, 0.5, 1.0)
    ]
    check("三点共线（盈亏电价对造价水平线性）",
          abs(points[0] + points[2] - 2 * points[1]) < 1e-9,
          f"{points[0]:.6f} / {points[1]:.6f} / {points[2]:.6f}")
    check("造价越高盈亏电价越高", points[0] < points[2])


def test_monotonic() -> None:
    if _skip("单调性"):
        return
    run = load_run(RUN_DIR)
    annualized = _annualized(run)
    for label, mode, degradation in (
        ("A", "replace", BASE_DEGRADATION),
        ("B", "replace", 0.0),
        ("C", "single", BASE_DEGRADATION),
    ):
        values = [
            scan_level(run, annualized, mode, degradation, level)["break_even_cny_per_kwh"]
            for level in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]
        check(f"{label} 口径随造价单调不减",
              all(values[i] <= values[i + 1] + 1e-9 for i in range(len(values) - 1)),
              f"{[round(v, 4) for v in values]}")


def test_thresholds() -> None:
    if _skip("门槛二分"):
        return
    run = load_run(RUN_DIR)
    annualized = _annualized(run)
    # A 与 B、C 的顺序关系必须成立：A 最贵 → 门槛最低
    level_a = find_threshold(run, annualized, "replace", BASE_DEGRADATION)
    level_b = find_threshold(run, annualized, "replace", 0.0)
    level_c = find_threshold(run, annualized, "single", BASE_DEGRADATION)
    check("A 口径存在门槛且在 (0,1) 内", level_a is not None and 0.0 < level_a < 1.0,
          f"实际 {level_a}")
    check("B 口径现价即成立", level_b is not None and level_b >= 1.0, f"实际 {level_b}")
    check("C 口径门槛高于 A（C 更便宜，能更早成立）",
          level_c is not None and level_a is not None and level_c > level_a,
          f"C={level_c}, A={level_a}")

    if level_a is not None and 0.0 < level_a < 1.0:
        below = scan_level(run, annualized, "replace", BASE_DEGRADATION, level_a - 0.02)
        above = scan_level(run, annualized, "replace", BASE_DEGRADATION, level_a + 0.02)
        check("门槛下方成立、上方不成立", below["viable"] and not above["viable"],
              f"{below['viable']} / {above['viable']}")


def test_viable_flag_matches_price() -> None:
    if _skip("viable 标志"):
        return
    run = load_run(RUN_DIR)
    annualized = _annualized(run)
    ok = True
    for level in (0.0, 0.1, 0.5, 0.9, 1.0):
        item = scan_level(run, annualized, "replace", BASE_DEGRADATION, level)
        ok = ok and item["viable"] == (item["break_even_cny_per_kwh"] < run["grid_price"])
        ok = ok and abs(item["multiple"] - item["break_even_cny_per_kwh"] / run["grid_price"]) < 1e-9
    check("viable 与 multiple 均由现价推出，前后一致", ok)


def main() -> int:
    test_reproduces_record_at_full_price()
    test_linear_in_capex_level()
    test_monotonic()
    test_thresholds()
    test_viable_flag_matches_price()

    print()
    if failures:
        print(f"{len(failures)} 项失败： {failures}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
