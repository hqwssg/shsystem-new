"""假设登记表 / 稳定性登记表 的一致性回归测试。

锁住三件事：

1. 两张表的字段契约（id 唯一、status 取值合法、必填字段在位）；
2. 交叉引用完整性：能力引用的假设必须已登记，证据路径必须真实存在
   —— 这一条最容易随代码重构失效（改了测试文件名没改登记表）；
3. 治理约束：``open`` 的能力必须说明"为什么没定案"；
   ``contested`` 的假设必须被至少一个 ``open`` 能力引用。

第 2 条是本轮真正踩到的：登记表里写了一个不存在的测试路径，
如果没有校验，前端会拿到一条指向空气的证据。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGISTRY = ROOT / "docs" / "algorithm_stability_registry.json"
ASSUMPTIONS = ROOT / "data" / "real_shuohuang" / "assumptions.json"

VALID_STATUS = {"locked", "conditional", "open", "superseded"}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    from tools.audit_algorithm_stability import build_matrix, validate

    print("稳定性登记表一致性")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assumptions = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))

    check("稳定性登记表存在且可解析", bool(registry.get("capabilities")))
    check("假设登记表存在且可解析", bool(assumptions.get("assumptions")))

    # ---- 字段契约 ----
    ids = [item["id"] for item in assumptions["assumptions"]]
    check("假设 id 唯一", len(ids) == len(set(ids)), f"{len(ids)} 条，去重后 {len(set(ids))}")

    legend = set(assumptions.get("status_legend", {}))
    bad_status = [
        item["id"] for item in assumptions["assumptions"]
        if item.get("status") not in legend
    ]
    check("每条假设的 status 都在 legend 内", not bad_status, str(bad_status))

    required = {"id", "title", "value", "status", "basis", "impact_outputs", "owner_to_confirm"}
    missing = [
        (item.get("id"), sorted(required - set(item)))
        for item in assumptions["assumptions"]
        if required - set(item)
    ]
    check("每条假设都有必填字段", not missing, str(missing))

    cap_status = [c.get("status") for c in registry["capabilities"]]
    check(
        "每条能力的 status 合法",
        set(cap_status) <= VALID_STATUS,
        str(sorted(set(cap_status) - VALID_STATUS)),
    )

    # ---- 交叉引用与治理约束 ----
    problems, warnings = validate(registry, assumptions)
    check("登记表交叉校验通过", not problems, "; ".join(problems[:3]))
    # outputs/ 下的证据是开发期产物，包内缺失只应产生警告，不应判失败。
    check(
        "开发期证据缺失只报警告",
        all("outputs/" in item for item in warnings),
        str([w for w in warnings if "outputs/" not in w][:3]),
    )

    # ---- 矩阵形态：前端消费契约 ----
    matrix = build_matrix(registry, assumptions)
    # 计数分档必须覆盖登记表里出现过的全部状态（含 superseded 这一历史档），
    # 且各档之和 = total = 能力条数；只断言三档的做法会漏掉后来新增的状态。
    present = {c.get("status") for c in registry["capabilities"]}
    counted = {key for key in matrix["counts"] if key != "total"}
    check(
        "矩阵计数覆盖全部能力状态且与能力数一致",
        present <= counted
        and sum(matrix["counts"][k] for k in counted) == matrix["counts"]["total"] == len(matrix["capabilities"]),
        str(matrix["counts"]),
    )
    check(
        "display 只有 direct / with_caveat 两种取值",
        {c["display"] for c in matrix["capabilities"]} <= {"direct", "with_caveat"},
        str({c["display"] for c in matrix["capabilities"]}),
    )
    # 无依赖的能力才允许直接展示，有依赖的一律带条件。
    wrong = [
        c["id"] for c in matrix["capabilities"]
        if (c["display"] == "direct") != (not c["assumptions"])
    ]
    check("display 与是否依赖假设一致", not wrong, str(wrong))
    check(
        "open 能力都会进入 blocked_outputs",
        all(
            c["name"] in matrix["blocked_outputs"].get(out, [])
            for c in matrix["capabilities"] if c["status"] == "open"
            for out in c["downstream"]
        ),
        str(matrix["blocked_outputs"]),
    )

    # ---- 阶段语义：联调可用 ≠ 结论可发布 ----
    phase = registry.get("phase")
    check("登记表声明了阶段", phase in (registry.get("phase_legend") or {}), str(phase))
    check(
        "矩阵透出阶段",
        matrix.get("phase") == phase,
        f"矩阵 {matrix.get('phase')} / 登记表 {phase}",
    )
    check(
        "ready_for_frontend 与 ready_for_conclusions 一致",
        matrix["ready_for_frontend"] == matrix["ready_for_conclusions"],
        str({k: matrix[k] for k in ("ready_for_frontend", "ready_for_conclusions")}),
    )
    check(
        "正式阶段且没有条件或未定案能力才允许发布结论",
        matrix["ready_for_conclusions"] == (
            phase == "production"
            and matrix["counts"]["locked"] > 0
            and matrix["counts"]["open"] == matrix["counts"]["conditional"] == 0
        ),
        f"open={matrix['counts']['open']}, conclusions={matrix['ready_for_conclusions']}",
    )
    check(
        "仿真阶段允许联调",
        matrix["ready_for_integration"]
        == (matrix["counts"]["total"] > 0 and (phase == "simulation" or matrix["ready_for_conclusions"])),
        f"phase={phase}, integration={matrix['ready_for_integration']}",
    )

    print()
    if failures:
        print(f"{len(failures)} 项失败：")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
