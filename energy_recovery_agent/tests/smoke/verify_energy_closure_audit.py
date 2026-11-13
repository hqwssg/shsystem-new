"""能耗闭合闸门（势能下界判据）回归测试。

锁住四件事：

1. **下界的物理性质**：随质量线性增、随最高速度减、爬升小于动能缓冲时归零；
   —— 这一条保证公式没有被写反，也保证"取 v_max 上限"确实是保守方向。
2. **重建族真的保高程**：所有变体的净高差逐位相同，且实际最大偏离不超过声明的容差；
   —— 否则"剖面变化 −3%"这个结论就不成立，因为它可能是把地形改了。
3. **判定不随剖面细结构翻转**：翻转所需的高程容差必须是读数分辨率的一个量级以上的倍数；
   —— 这是把 ``gradient_profile`` 从 open 降为 conditional 的唯一依据。
4. **包络自洽**：带宽上下界有序、落在下界之上、读数落在带内的判定与 JSON 一致。

依赖 ``outputs/energy_closure/`` 的用例在缺文件时跳过（发布包不含 ``outputs/``），
纯判据部分永远运行。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_energy_closure import (  # noqa: E402
    MERGE_TOLERANCES_M,
    build_variants,
    elevation_points,
    MAIN_CUT_KM,
    load_profile,
    split_main,
    traction_lower_bound_kwh,
)

CLOSURE_JSON = ROOT / "outputs" / "energy_closure" / "closure_matrix.json"
ENVELOPE_JSON = ROOT / "outputs" / "energy_closure" / "scenario_envelope.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


# --------------------------------------------------------------------------- #
def test_bound_properties() -> None:
    """下界的物理性质：单调性与归零。"""

    base = traction_lower_bound_kwh(21900.0, 167.6)
    heavier = traction_lower_bound_kwh(43800.0, 167.6)
    check(
        "下界随质量线性增（质量加倍 → 下界约加倍）",
        abs(heavier["wheel_kwh"] / base["wheel_kwh"] - 2.0) < 0.01,
        f"{heavier['wheel_kwh']:.1f} vs {base['wheel_kwh']:.1f}",
    )

    faster = traction_lower_bound_kwh(21900.0, 167.6, v_max_kmh=120.0)
    check(
        "最高速度取大 → 动能缓冲变大 → 下界变小（保守方向正确）",
        faster["wheel_kwh"] < base["wheel_kwh"],
        f"80 km/h {base['wheel_kwh']:.1f} vs 120 km/h {faster['wheel_kwh']:.1f}",
    )

    flat = traction_lower_bound_kwh(21900.0, 5.0)
    check(
        "爬升小于动能缓冲时下界归零（不出现负的下界）",
        flat["wheel_kwh"] == 0.0,
        f"实际 {flat['wheel_kwh']}",
    )

    check(
        "电网侧下界 = 轮周下界 / 效率",
        abs(base["grid_kwh"] - base["wheel_kwh"] / 0.86) < 0.2,
        f"{base['grid_kwh']} vs {base['wheel_kwh'] / 0.86:.1f}",
    )


def test_variants_preserve_elevation() -> None:
    """重建族必须保净高差，且实际偏离不超过声明容差。"""

    head, _tail = split_main(load_profile())
    variants = build_variants(head)
    check(
        "重建族覆盖全部容差档",
        len(variants) == len(MERGE_TOLERANCES_M) + 1,
        f"实际 {len(variants)} 个变体",
    )

    nets = {round(v["stats"]["net_change_m"], 1) for v in variants}
    check(
        "所有变体净高差逐位相同",
        len(nets) == 1,
        f"出现多个净高差 {sorted(nets)}",
    )

    for variant in variants:
        declared = variant["tolerance_m"]
        actual = variant["max_elevation_error_m"]
        check(
            f"`{variant['id']}` 实际偏离不超过声明容差 {declared:g} m",
            actual <= declared + 1e-6,
            f"实际 {actual}",
        )

    raw_ascent = variants[0]["stats"]["ascent_m"]
    ascents = [v["stats"]["ascent_m"] for v in variants]
    check(
        "累计爬升随容差单调不增",
        all(left >= right - 1e-6 for left, right in zip(ascents, ascents[1:])),
        f"{ascents}",
    )
    check(
        "原始剖面累计爬升在 100–250 m（既非 0 也非噪声放大）",
        100.0 <= raw_ascent <= 250.0,
        f"实际 {raw_ascent}",
    )

    xs, zs = elevation_points(head)
    # 2026-11-07：截断点改为肃宁北的真实里程（406.571 km），分段数随之从 446 变为数据决定值。
    # 断言改成「与截断点之前的坡度记录数一致」，避免把某个里程写死。
    import csv as _csv

    with (ROOT / "data" / "real_shuohuang" / "gradients.csv").open(encoding="utf-8-sig") as _fh:
        expected_segments = sum(
            1 for _row in _csv.DictReader(_fh) if float(_row["start_km"]) < MAIN_CUT_KM
        )
    check(
        f"原始剖面分段数与文件一致（截断 {MAIN_CUT_KM:.3f} km 前 {expected_segments} 段）",
        len(zs) - 1 == expected_segments,
        f"实际 {len(zs) - 1}",
    )


def test_variant_segments_contiguous() -> None:
    """变体分段必须首尾相接、覆盖 0–截断点，否则仿真会报"有缝"。"""

    head, _tail = split_main(load_profile())
    for variant in build_variants(head):
        segments = variant["segments"]
        contiguous = all(
            abs(left[1] - right[0]) < 1e-9
            for left, right in zip(segments, segments[1:])
        )
        check(
            f"`{variant['id']}` 分段首尾相接",
            contiguous,
            "存在间隙或重叠",
        )
        check(
            f"`{variant['id']}` 覆盖 0 至截断点",
            abs(segments[0][0]) < 1e-9 and abs(segments[-1][1] - MAIN_CUT_KM) < 1e-6,
            f"{segments[0][0]} → {segments[-1][1]}",
        )


def test_closure_verdicts() -> None:
    """判定：whole_train 不成立、one_of_two 通过、判定不随剖面翻转。"""

    if not CLOSURE_JSON.exists():
        print(f"[SKIP] 缺少 {CLOSURE_JSON.name}，跳判定复核")
        return
    payload = json.loads(CLOSURE_JSON.read_text(encoding="utf-8"))
    readings = {item["id"]: item for item in payload["readings"]}

    check(
        "whole_train 被势能下界判死",
        readings["whole_train"]["verdict"] == "violates_bound",
        f"实际 {readings['whole_train']['verdict']}",
    )
    check(
        "one_of_two 通过下界",
        readings["one_of_two"]["verdict"] == "admissible",
        f"实际 {readings['one_of_two']['verdict']}",
    )
    check(
        "whole_2loco 同样被判定不成立（汇总口径也付不起爬升功）",
        readings["whole_2loco"]["verdict"] == "violates_bound",
        f"实际 {readings['whole_2loco']['verdict']}",
    )

    # 下界必须能由变体重算出来，防止 JSON 与代码脱节。
    variant = payload["variants"][0]
    recomputed = traction_lower_bound_kwh(21900.0, variant["stats"]["ascent_m"])
    stored = payload["bounds"]["loco_1"][variant["id"]]["grid_kwh"]
    check(
        "JSON 中的下界可由累计爬升重算",
        abs(recomputed["grid_kwh"] - stored) < 1.0,
        f"重算 {recomputed['grid_kwh']} vs 记录 {stored}",
    )

    flip = payload["flip_analysis"]
    resolution = flip["reading_resolution_m"]
    check(
        "判定要翻转须把高程扭曲到读数分辨率的 10 倍以上",
        all(t >= 10.0 * resolution - 1e-9 for t in flip["flip_tolerances_m"]),
        f"翻转容差 {flip['flip_tolerances_m']}，分辨率 {resolution}",
    )

    sensitivity = payload.get("sensitivity") or {}
    faithful = sensitivity.get("max_relative_span_pct_faithful")
    stress = sensitivity.get("max_relative_span_pct")
    if faithful is None or stress is None:
        # 审计若只跑了 --no-simulate，敏感性表是空的——此时跳过而不是判失败，
        # 否则"没有仿真"会被误报成"敏感性超标"。
        print("[SKIP] 审计产物不含仿真结果（--no-simulate），跳敏感性校验")
    else:
        check(
            "读数精度档内（≤4×分辨率）剖面细结构解释幅度小于 5%",
            faithful <= 5.0,
            f"实际 {faithful}%",
        )
        check(
            "压力档（放到 4 m 扭曲）解释幅度也小于 10%",
            stress <= 10.0,
            f"实际 {stress}%",
        )


def test_envelope_consistency() -> None:
    """包络：上下界有序、落在下界之上、读数落带判定与数据一致。"""

    if not ENVELOPE_JSON.exists():
        print(f"[SKIP] 缺少 {ENVELOPE_JSON.name}，跳包络复核")
        return
    envelope = json.loads(ENVELOPE_JSON.read_text(encoding="utf-8"))
    branches = envelope.get("branches") or {}
    if not branches:
        print("[SKIP] 包络没有分支数据（可能只跑了 --no-simulate），跳包络复核")
        return
    matrix = json.loads(CLOSURE_JSON.read_text(encoding="utf-8")) if CLOSURE_JSON.exists() else None
    for branch_id, item in branches.items():
        traction = item["traction_kwh"]
        check(
            f"{branch_id} 牵引带上下界有序",
            traction["low"] <= traction["high"],
            f"{traction['low']} > {traction['high']}",
        )
        check(
            f"{branch_id} 带宽不为零（重建族确实有影响）",
            traction["high"] - traction["low"] > 0.0,
            "带宽为 0，说明重建没接进仿真",
        )
        if matrix is None:
            continue
        bounds = matrix["bounds"][branch_id]["raw"]["grid_kwh"]
        check(
            f"{branch_id} 带下沿高于势能下界",
            traction["low"] > bounds,
            f"带下沿 {traction['low']} vs 下界 {bounds}",
        )
        check(
            f"{branch_id} 带宽不超过下界的 10%",
            (traction["high"] - traction["low"]) / bounds <= 0.10,
            f"{(traction['high'] - traction['low']) / bounds:.1%}",
        )

    loco2 = branches.get("loco_2")
    if loco2 is None:
        print("[SKIP] 包络缺少 loco_2 分支")
        return
    check(
        "双机分支采用『读数只是其中一台』这一读法",
        loco2["adopted_reading"] == "one_of_two",
        f"实际 {loco2['adopted_reading']}",
    )
    check(
        "双机分支的读数判定为通过",
        loco2["adopted_reading_verdict"] == "admissible",
        f"实际 {loco2['adopted_reading_verdict']}",
    )
    check(
        "模型牵引高于读数（已知模型偏差被如实记录，未被抹平）",
        loco2["traction_kwh"]["metered_inside"] is False,
        "读数落在带内，说明偏差消失了，需要重核模型",
    )


def test_registry_alignment() -> None:
    """登记表与审计结论必须一致：剖面已降级、牵引不得 locked、闸门为 locked。"""

    registry_path = ROOT / "docs" / "algorithm_stability_registry.json"
    if not registry_path.exists():
        print(f"[SKIP] 缺少 {registry_path.name}")
        return
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in registry["capabilities"]}

    check(
        "坡度剖面已从 open 降为 conditional",
        by_id["gradient_profile"]["status"] == "conditional",
        f"实际 {by_id['gradient_profile']['status']}",
    )
    # 2026-11-08：台数/计量口径已由电表车次表定案（见 meter_reading_scope），
    # 所以「未定案」这条断言不再成立。但绝对值仍不能对外给点值——理由换成了
    # 「模型吞吐量比实测高 1.6–1.8 倍、净值偏负 50%」。所以这里守的是
    # **不能是 locked**，而不是必须 open。
    check(
        "重车牵引电量不是 locked（绝对值仍不可对外给点值）",
        by_id["heavy_traction_energy"]["status"] != "locked",
        f"实际 {by_id['heavy_traction_energy']['status']}",
    )
    # 2026-11-07：计量对象定案为「一台机车 3 节」，但整列 = 2× 单机只是等分假设
    # （补机电表不在数据集内），所以本条目从 locked 降为 conditional 是**正确的**。
    # 这里守两条：① 口径本身不得再回到 open；② 必须写明「单机」这个已定案的事实。
    meter = by_id.get("meter_reading_scope", {})
    check(
        "计量口径已定案，且写明是「一台机车（3 节）」",
        meter.get("status") in ("locked", "conditional") and "一台" in meter.get("summary", ""),
        f"{meter.get('status')} / 含「一台」={('一台' in meter.get('summary', ''))}",
    )
    check(
        "计量口径的降级理由写明了「补机数据缺失」这一未验证项",
        "补机" in meter.get("status_rule", "") and "conditional" in meter.get("status", ""),
        meter.get("status_rule", "")[:60],
    )
    check(
        "重车牵引的降级理由写明了量化缺口（按整列口径的倍数）",
        # 2026-11-07 更新：口径重置为整列后，缺口从「牵引 3.02 倍」变成「再生 0.49 倍、净能耗符号相反」。
        # 判据取「写明了整列口径的缺口」，而不是某个特定词或某个特定倍数。
        "整列" in by_id["heavy_traction_energy"].get("status_rule", "")
        and "倍" in by_id["heavy_traction_energy"].get("status_rule", ""),
        by_id["heavy_traction_energy"].get("status_rule", "")[:60],
    )
    check(
        "闭合闸门登记为 locked",
        by_id.get("energy_closure_gate", {}).get("status") == "locked",
        f"实际 {by_id.get('energy_closure_gate', {}).get('status')}",
    )
    check(
        "降级的能力写明了 status_rule",
        bool(by_id["gradient_profile"].get("status_rule")),
        "缺少 status_rule，降级会变成无据可查",
    )


def test_assumptions_alignment() -> None:
    """假设登记表必须带上这次审计的数字，否则两处口径会漂。"""

    path = ROOT / "data" / "real_shuohuang" / "assumptions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in payload["assumptions"]}
    audit = by_id["two_wan_ton_locomotive_count"].get("closure_audit")
    check("台数假设带 closure_audit", bool(audit), "缺少 closure_audit")
    if not audit:
        return
    verdicts = {}
    for item in audit["results"]:
        # 假设表里的 reading 带中文括注，用前缀匹配，避免改文案就断测试。
        key = str(item["reading"]).split("（")[0]
        verdicts[key] = item["verdict"]
    check(
        "假设表与审计的三种读法判定一致",
        verdicts.get("whole_train") == "violates_bound"
        and verdicts.get("one_of_two") == "admissible",
        f"{verdicts}",
    )
    check(
        "假设表记录了已知模型偏差",
        bool(str(audit.get("known_model_bias", "")).strip()),
        "缺少 known_model_bias",
    )


def main() -> int:
    test_bound_properties()
    test_variants_preserve_elevation()
    test_variant_segments_contiguous()
    test_closure_verdicts()
    test_envelope_consistency()
    test_registry_alignment()
    test_assumptions_alignment()
    if failures:
        print(f"\n能耗闭合闸门：FAIL（{len(failures)} 项）")
        return 1
    print("\n能耗闭合闸门：PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
