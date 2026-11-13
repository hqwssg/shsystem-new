"""输入完整性门禁的回归测试。

锁住四件事：

1. 槽位清单的字段契约（id 唯一、规则已实现、来源取值合法）；
2. **不存在必填空槽** —— 这是本轮的交付目标：仿真阶段算法必须端到端能跑，
   缺真实数据就用虚拟值填，但不许留空；
3. 每个虚拟槽位都能追溯到 ``assumptions.json`` 的一条假设
   —— 否则虚拟值会变成「谁也不知道为什么是这个数」的暗值；
4. ``--strict`` 的语义：只有虚拟槽位为零（真数据齐备）才应通过。

第 3 条是本轮真正想防的退化：以后有人为了跑通而在 CSV 里塞一个数，
只要没有对应的假设登记，这个测试就会红。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGISTRY = ROOT / "docs" / "input_completeness_registry.json"
ASSUMPTIONS = ROOT / "data" / "real_shuohuang" / "assumptions.json"

VALID_SOURCE = {"measured", "derived", "virtual", "optional_blank", "not_modeled"}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    from tools.audit_input_completeness import RULES, evaluate

    print("输入完整性门禁")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assumptions = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))
    slots = registry["slots"]

    ids = [slot["id"] for slot in slots]
    check("槽位清单非空且 id 唯一", bool(ids) and len(ids) == len(set(ids)), f"{len(ids)} 条")

    unknown_rule = [slot["id"] for slot in slots if slot["rule"] not in RULES]
    check("每条槽位的规则都已实现", not unknown_rule, str(unknown_rule))

    declared_rules = set(registry.get("rules", {}))
    undeclared = sorted({slot["rule"] for slot in slots} - declared_rules)
    check("用到的规则都在 rules 说明段里登记", not undeclared, str(undeclared))

    bad_source = [slot["id"] for slot in slots if slot.get("source") not in VALID_SOURCE]
    check("来源取值合法", not bad_source, str(bad_source))

    required_fields = {"id", "file", "rule", "required", "source"}
    missing = [(slot.get("id"), sorted(required_fields - set(slot))) for slot in slots]
    check("每条槽位都有必填字段", all(not diff for _, diff in missing), str(missing[:3]))

    results, stats = evaluate(registry)
    check(
        "不存在必填空槽（算法端到端可运行）",
        stats["failed_required"] == 0,
        f"{stats['failed_required']} 个必填槽位失败："
        + "; ".join(f"{r.slot['id']}: {r.detail}" for r in results if not r.passed and r.required)[:200],
    )

    assumption_ids = {item["id"] for item in assumptions["assumptions"]}
    virtual = [slot for slot in slots if slot.get("source") == "virtual"]
    check("存在虚拟填充槽位时都能给出数量", len(virtual) == len(stats["virtual_slots"]), f"{len(virtual)} 个")

    untraceable = [slot["id"] for slot in virtual if not slot.get("assumption_id")]
    check("每个虚拟槽位都带 assumption_id", not untraceable, str(untraceable))

    dangling = [
        (slot["id"], slot["assumption_id"])
        for slot in virtual
        if slot.get("assumption_id") and slot["assumption_id"] not in assumption_ids
    ]
    check("虚拟槽位指向的假设都已登记", not dangling, str(dangling))

    # 覆盖率类槽位必须真的覆盖到全线末端，避免「文件存在就算通过」。
    covered = {r.slot["id"] for r in results if r.slot["rule"] == "coverage" and r.passed}
    check("至少两个覆盖类槽位通过（坡度 + 限速）", len(covered) >= 2, str(sorted(covered)))

    extent = stats["extent_km"]
    check("全线长度取自站点表末端", 580.0 < extent < 600.0, f"{extent}")

    # 电分相：登记为「可推导、未接入」，必须能报出数量，否则说明边界数据退化。
    phase = next((r for r in results if r.slot["id"] == "phase_breaks"), None)
    check("电分相边界可推导且已登记", phase is not None and phase.passed, phase.detail if phase else "缺少槽位")
    if phase is not None and phase.passed:
        breaks = phase.extra.get("by_direction", {}).get("上行", {}).get("breaks", 0)
        check("上行电分相数量与供电臂一致（30 处）", breaks == 30, f"实际 {breaks}")

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for name in failures:
            print(f"  - {name}")
        return 1
    print(f"全部通过（{stats['slot_count']} 个槽位，{len(virtual)} 个虚拟填充）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
