"""真实数据是否真的进了模型（而不是只躺在 data/ 里）。

这个测试守的是「接线」本身：每条真实数据都要能在模型对象里读出对应字段，
否则报告里写了、模型里没用，等于没接。

覆盖六条：
1. 编组：`trains.csv` → 1+1 两台，整列 22,100 t / 24,000 kW
2. 机型：`SHENHUA_8` 存在且为 8 轴 200 t 9600 kW
3. 里程：主 OD 终点 = `stations.csv` 的肃宁北，且不再是硬编码 396
4. 曲线：`segments.csv` 的 `curve_radius_m` 已填充，仿真器会按 600/R 计入
5. 区间时分：`section_run_times.csv` 覆盖 22 个区间，且起停附加齐全
6. 端到端：跑一次重车，净值必须为负（与实测「重车净发电」同号）
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "data" / "real_shuohuang"
PASSED = 0
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
    else:
        FAILED += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    from locomotive_curves import default_curve_bank
    from train_simulator import consist_mass_tons, normalise_locomotive_consist

    print("真实数据接线：")

    # ---------------- 1. 编组 ----------------
    rows = list(csv.DictReader((DATA / "trains.csv").open(encoding="utf-8-sig")))
    heavy = next((r for r in rows if r["name"] == "Heavy"), None)
    check("trains.csv 有 Heavy 行", heavy is not None)
    consist = normalise_locomotive_consist(
        tuple(
            (chunk.split(":")[0], int(chunk.split(":")[1]))
            for chunk in (heavy.get("locomotive_consist") or "").split("|")
            if ":" in chunk
        )
    ) if heavy else ()
    check(
        "重车编组清单为 1+1 两台",
        len(consist) == 2 and sum(c for _, c in consist) == 2,
        str(consist),
    )
    check(
        "编组含 12 轴与 8 轴两种机型",
        {t for t, _ in consist} == {"SHENHUA_12", "SHENHUA_8"},
        str([t for t, _ in consist]),
    )
    loco_mass = consist_mass_tons(consist)
    check("机车整备质量 500 t（300 + 200）", abs(loco_mass - 500.0) < 1e-6, f"{loco_mass:.1f} t")

    # ---------------- 2. 机型 ----------------
    bank = default_curve_bank()
    p8 = bank.locomotive_params("SHENHUA_8") or {}
    check("SHENHUA_8 已登记", bool(p8))
    check("SHENHUA_8 为 8 轴 200 t", p8.get("axle_count") == 8 and p8.get("computed_mass_t") == 200.0,
          f"{p8.get('axle_count')} 轴 / {p8.get('computed_mass_t')} t")
    check("SHENHUA_8 功率 9,600 kW", p8.get("continuous_power_kW") == 9600.0,
          str(p8.get("continuous_power_kW")))
    p12 = bank.locomotive_params("SHENHUA_12") or {}
    check(
        "12 轴功率恰为 8 轴的 1.5 倍（同族校验）",
        abs(p12.get("continuous_power_kW", 0) - 1.5 * p8.get("continuous_power_kW", 0)) < 1e-6,
        f"{p12.get('continuous_power_kW')} vs 1.5×{p8.get('continuous_power_kW')}",
    )

    # ---------------- 3. 里程 ----------------
    from tools.attribute_traction_energy import MAIN_OD_KM

    stations = {
        r["name"].strip(): float(r["position_km"])
        for r in csv.DictReader((DATA / "stations.csv").open(encoding="utf-8-sig"))
    }
    check(
        "主 OD 终点 = stations.csv 的肃宁北",
        abs(MAIN_OD_KM - stations["肃宁北"]) < 1e-6,
        f"{MAIN_OD_KM} vs {stations['肃宁北']}",
    )
    check("主 OD 不再是硬编码 396.0", abs(MAIN_OD_KM - 396.0) > 1.0, f"{MAIN_OD_KM}")

    # 区间公里合计应与车站表一致（用 JSON 转录版）
    import json as _json

    transcribed = _json.loads((DATA / "section_run_times_2026.json").read_text(encoding="utf-8"))
    total_km = sum(row[3] for row in transcribed["sections"])
    check(
        "运行图区间公里合计 ≈ 车站表肃宁北里程（±0.5 km）",
        abs(total_km - stations["肃宁北"]) <= 0.5,
        f"{total_km:.1f} vs {stations['肃宁北']:.3f}",
    )

    # ---------------- 4. 曲线 ----------------
    segments = list(csv.DictReader((DATA / "segments.csv").open(encoding="utf-8-sig")))
    with_radius = sum(1 for r in segments if (r.get("curve_radius_m") or "").strip())
    check(
        "segments.csv 有曲线半径（曲线附加阻力可算）",
        with_radius >= 300,
        f"{with_radius}/{len(segments)} 段",
    )
    check(
        "曲线段占比在 25%–50%",
        0.25 <= with_radius / max(len(segments), 1) <= 0.50,
        f"{with_radius / max(len(segments), 1):.0%}",
    )

    # ---------------- 5. 区间时分 ----------------
    times = list(csv.DictReader((DATA / "section_run_times.csv").open(encoding="utf-8-sig")))
    classes = {(r.get("quantity") or "").strip() for r in times}
    check(
        "区间时分含 run_time / start_add / stop_add 三类",
        {"run_time", "start_add", "stop_add"} <= classes,
        str(sorted(classes)[:5]),
    )
    sections = {
        (r["start_station"], r["end_station"])
        for r in times
        if r["direction"] == "up" and r["quantity"] == "run_time"
    }
    check("上行区间数 ≥ 22", len(sections) >= 22, f"{len(sections)} 段")

    # ---------------- 6. 端到端 ----------------
    from tools.attribute_traction_energy import run_case

    summary = run_case(None, 10, 0.48, "wire", schedule_speed_cap="dwell")["summary"]
    check(
        "重车整列质量 22,100 t",
        abs(summary["mass_t"] - 22100.0) < 1.0,
        f"{summary['mass_t']:.0f} t",
    )
    check(
        "功率上限 24,000 kW",
        abs(summary["power_cap_kW"] - 24000.0) < 1.0,
        f"{summary['power_cap_kW']:.0f} kW",
    )
    check(
        "重车净值为负（与实测「重车净发电」同号）",
        summary["total_regen_kwh"] > summary["total_traction_kwh"],
        f"{summary['total_traction_kwh']:.0f} − {summary['total_regen_kwh']:.0f}",
    )

    # ---------------- 7. 实测目标只有一个来源 ----------------
    # 2026-11-08 修过的 bug：`attribute_traction_energy` 写 6,322×2=12,644，
    # `build_flight_profile` 写死 12,456，两个目标并存。这里锁死「唯一来源」。
    import json as _json

    from tools import attribute_traction_energy as _attr
    from tools.build_flight_profile import TARGET as _flight_target

    scope_path = ROOT / "outputs" / "meter_scope" / "meter_scope.json"
    if scope_path.exists():
        scope = _json.loads(scope_path.read_text(encoding="utf-8"))["heavy_two_wan"]
        scope_gross = float(scope["gross_kwh"]["median"])
        check(
            "整列目标 = 口径工具的单机中位 × 2",
            abs(_attr.WHOLE_TRAIN_METERED_KWH - scope_gross * 2.0) < 1.0,
            f"{_attr.WHOLE_TRAIN_METERED_KWH:,.1f} vs {scope_gross * 2.0:,.1f}",
        )
        check(
            "前瞻剖面用的目标与本模块一致（不再各写一份）",
            abs(_flight_target["traction_kwh"] - _attr.WHOLE_TRAIN_METERED_KWH) < 1.0,
            f"{_flight_target['traction_kwh']:,.1f} vs {_attr.WHOLE_TRAIN_METERED_KWH:,.1f}",
        )
    check(
        "级位标定窗口与实际运行窗口同里程（不写死 396）",
        abs(_attr.MAIN_OD_KM - 406.571) < 0.5,
        f"{_attr.MAIN_OD_KM:.3f} km",
    )

    print()
    print(f"真实数据接线：{'PASS' if FAILED == 0 else 'FAIL'}（{PASSED}/{PASSED + FAILED}）")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
