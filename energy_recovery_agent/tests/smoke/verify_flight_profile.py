"""前瞻速度剖面的口径断言。

守四件事：

1. 剖面确实来自图定表（22 段、393 min、406.5 km），不是凭空造的曲线。
2. 惰行包络的求解方向正确——目标时分越紧，下限比例越高、牵引越大。
3. 前沿单调：放松时分必然省电，且**实测点落在这条前沿的下方**（本轮核心结论）。
4. 报告写明了「目标低于当前速度就是制动指令」这条机制，否则读者会以为形状剖面
   也能省电。

依赖 ``outputs/flight_profile/``；缺文件时跳过（发布包不含 outputs/）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JSON_PATH = ROOT / "outputs" / "flight_profile" / "flight_profile.json"
MD_PATH = ROOT / "outputs" / "flight_profile" / "前瞻剖面报告.md"

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
    if not JSON_PATH.exists():
        print(f"跳过：缺少 {JSON_PATH}")
        return 0

    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    target = payload["target"]
    frontier = payload["frontier"]
    reactive = payload["reactive"]
    timeline = payload["calibration"]
    sections = payload["sections"]

    print("前瞻速度剖面：")

    # ---- 1. 剖面来源 ----
    check("剖面覆盖 22 个图定区间", len(sections) == 22, f"{len(sections)} 段")
    check(
        "图定时分合计 393 min",
        abs(payload["timetable_minutes"] - 393.0) < 1e-6,
        f"{payload['timetable_minutes']}",
    )
    check(
        "剖面里程与车站表一致（406.5 km）",
        abs(payload["distance_km"] - 406.571) < 0.5,
        f"{payload['distance_km']} km",
    )
    check(
        "剖面速度不超过线路允许速度（≤78.5 km/h）",
        all(item["max_speed_kmh"] <= 78.5 for item in sections),
        f"最大 {max(item['max_speed_kmh'] for item in sections):.1f}",
    )
    check(
        "剖面存在速度浮动（不是恒速）",
        max(item["max_speed_kmh"] for item in sections)
        - min(item["min_speed_kmh"] for item in sections)
        > 10.0,
        f"{min(item['min_speed_kmh'] for item in sections):.0f}–"
        f"{max(item['max_speed_kmh'] for item in sections):.0f} km/h",
    )

    # ---- 2. 求解方向 ----
    ordered = sorted(frontier, key=lambda row: row["minutes"])
    check(
        "放松时分 → 下限比例单调不增",
        all(b["floor_ratio"] <= a["floor_ratio"] + 1e-6 for a, b in zip(ordered, ordered[1:])),
        " → ".join(f"{row['floor_ratio']:.2f}" for row in ordered),
    )
    tractions = [row["traction_kwh"] for row in ordered]
    check(
        "放松时分 → 牵引单调不增",
        all(b <= a + 1.0 for a, b in zip(tractions, tractions[1:])),
        " → ".join(f"{value:,.0f}" for value in tractions),
    )
    minutes = [row["minutes"] for row in ordered]
    check(
        "实际时分随目标单调不减",
        all(b >= a - 1e-6 for a, b in zip(minutes, minutes[1:])),
        " → ".join(f"{value:.0f}" for value in minutes),
    )

    # ---- 3. 核心结论：实测点在前沿下方 / 不在可行域内 ----
    at_measured = payload.get("frontier_at_measured_minutes")
    check(
        "前沿在实测时分处的牵引高于实测（或实测时分越界已记录）",
        (at_measured is not None and at_measured > target["traction_kwh"])
        or (at_measured is None and payload.get("model_min_minutes") is not None),
        f"{at_measured}",
    )
    model_min = payload.get("model_min_minutes")
    model_min_traction = payload.get("model_min_minutes_traction_kwh")
    check(
        "模型最快时分的牵引高于实测（最保守一档也追不上）",
        model_min_traction is not None and model_min_traction > target["traction_kwh"],
        f"{model_min_traction:,.0f} vs {target['traction_kwh']:,.0f}" if model_min_traction else "缺值",
    )
    check(
        "模型最快时分与实测可对照（记录在 400–440 min）",
        model_min is not None and 400.0 <= model_min <= 440.0,
        f"{model_min}",
    )
    check(
        "反应式基线与前沿最紧一档同量级",
        reactive["traction_kwh"] >= ordered[0]["traction_kwh"] * 0.6,
        f"反应式 {reactive['traction_kwh']:,.0f} vs 最紧 {ordered[0]['traction_kwh']:,.0f}",
    )

    # ---- 4. 闭环校正 ----
    check("闭环校正至少跑了一轮", len(timeline) >= 1, f"{len(timeline)} 轮")
    desired = payload["timetable_minutes"] + payload["dwell_minutes"]
    if len(timeline) >= 2:
        first_error = abs(timeline[0]["actual_minutes"] - desired)
        last_error = abs(timeline[-1]["actual_minutes"] - desired)
        check(
            "闭环校正把实际时分向「图定 + 途停」收敛",
            last_error < first_error or last_error <= 3.0,
            f"{first_error:.0f} → {last_error:.0f} min",
        )
    check(
        "途停分钟取自 station_dwell.csv（25 min）",
        abs(payload["dwell_minutes"] - 25.0) < 1e-6,
        f"{payload['dwell_minutes']}",
    )

    # ---- 5. 分析结果与剖面同源（防 --no-scan 覆盖） ----
    fingerprint = payload.get("profile_fingerprint")
    check("分析结果带剖面指纹", bool(fingerprint), f"{fingerprint}")
    csv_path = JSON_PATH.parent / "flight_profile.csv"
    if fingerprint and csv_path.exists():
        import hashlib

        digest = hashlib.sha256()
        with csv_path.open(encoding="utf-8") as handle:
            next(handle)  # 表头
            for line in handle:
                position, speed = line.strip().split(",")
                digest.update(f"{position}:{speed};".encode("ascii"))
        check(
            "flight_profile.json 与 flight_profile.csv 同源（指纹一致）",
            digest.hexdigest()[:16] == fingerprint,
            f"csv {digest.hexdigest()[:16]} vs json {fingerprint}",
        )
    check(
        "analysis 结果未被 --no-scan 覆盖（含 frontier 与 calibration）",
        "frontier" in payload and "calibration" in payload,
    )

    # ---- 6. 报告文本 ----
    if MD_PATH.exists():
        text = MD_PATH.read_text(encoding="utf-8")
        check(
            "报告写明了「目标低于当前速度就是制动指令」的机制",
            "制动指令" in text and "coast_band" in text,
        )
        check(
            "报告给出了势能与耗散口径",
            "势能" in text and "差额" in text,
        )
        check(
            "报告没有把「形状剖面」当成可行方案",
            "不但不能省电" in text or "反而更费" in text,
        )
    else:
        check("报告存在", False, str(MD_PATH))

    print()
    print(f"通过 {PASSED}，失败 {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
