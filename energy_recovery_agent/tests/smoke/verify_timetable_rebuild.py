"""实测运行图重建工具的回归测试。

锁住四件事：

1. **站名归一**：实测表写 ``肃宁北Ⅱ场``，站表写 ``肃宁北``，不归一就会被静默丢掉；
2. **跨零点写成 24:xx 而不是回绕**：回绕会让运行图校验报「到发时刻倒退」，
   而这个错误在 396 km / 7—8 h 的重载运行里是常态，不是边缘情况；
3. **调车段要丢掉**：实测表末尾有一条 ``肃宁北Ⅱ场→肃宁北Ⅱ场`` 的 3 km 入库移动，
   计进去会凭空多出里程和时间；
4. **重建出来的运行图必须时刻单调、站序单调**：这是下游结算能跑的前提。

依赖真实 CSV 的用例在文件缺失时跳过（发布包不含 ``shuohuang_data/``）。
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_timetable_from_telemetry import (  # noqa: E402
    TELEMETRY,
    _format,
    _trip_rows,
    build_day,
    classify,
    load_trips,
    resolve_station,
    station_positions,
    write_workbook,
)
from timetable_input import load_canonical_timetable

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def _section(origin, destination, start, end):
    return {
        "start_station": origin,
        "end_station": destination,
        "starttime": f"2026-06-13 {start}",
        "endtime": f"2026-06-13 {end}",
    }


def test_station_resolution() -> None:
    positions = station_positions()
    check("站表能读到肃宁北", "肃宁北" in positions, f"实际 {sorted(positions)[:5]}")
    check(
        "肃宁北Ⅱ场 归一到 肃宁北",
        resolve_station("肃宁北Ⅱ场", positions) == "肃宁北",
        f"实际 {resolve_station('肃宁北Ⅱ场', positions)}",
    )
    check(
        "未知站名返回 None 而不是抛错",
        resolve_station("不存在的站", positions) is None,
        "未返回 None",
    )


def test_cross_midnight_format() -> None:
    check("零点写成 00:00:00", _format(0) == "00:00:00", _format(0))
    check("23:59:59 正常", _format(86399) == "23:59:59", _format(86399))
    check(
        "跨零点顺延到 25:00:00 而不是回绕",
        _format(90000) == "25:00:00",
        _format(90000),
    )


def test_yard_move_dropped() -> None:
    positions = station_positions()
    anchor = datetime.strptime("2026-06-13 00:00:00", "%Y-%m-%d %H:%M:%S")
    rows = [
        _section("神池南", "宁武西", "00:10:00", "00:50:00"),
        _section("宁武西", "肃宁北Ⅱ场", "00:50:00", "07:00:00"),
        _section("肃宁北Ⅱ场", "肃宁北Ⅱ场", "07:00:00", "07:12:00"),
    ]
    out = _trip_rows(rows, "H001", positions, anchor)
    stations = [row[2] for row in out]
    check(
        "同站调车段被丢弃（只剩 3 站）",
        stations == ["神池南", "宁武西", "肃宁北"],
        f"实际 {stations}",
    )
    check(
        "末站到达时刻取调车之前的到达，不是调车之后",
        out[-1][4] == "07:00:00",
        f"实际 {out[-1][4]}",
    )
    check("首站标 origin、末站标 terminal", out[0][6] == "origin" and out[-1][6] == "terminal",
          f"{out[0][6]}/{out[-1][6]}")


def test_classify_requires_full_trip() -> None:
    positions = station_positions()
    short = [_section("神池南", "宁武西", "00:10:00", "00:50:00")]
    check("短程记录不当作整趟", classify(short) is None, "被误判为整趟")

    full = [_section("神池南", f"S{i}", "00:00:00", "00:10:00") for i in range(23)]
    full[-1]["end_station"] = "肃宁北Ⅱ场"
    check("23 区间 + 主 OD 判为 Heavy", classify(full) == "Heavy", f"实际 {classify(full)}")

    reverse = [_section("肃宁北Ⅱ场", f"S{i}", "00:00:00", "00:10:00") for i in range(23)]
    reverse[-1]["end_station"] = "神池南"
    check("反向判为 Empty", classify(reverse) == "Empty", f"实际 {classify(reverse)}")


def test_arrival_departure_and_rejection() -> None:
    positions = {"神池南": 0, "宁武西": 15.931, "肃宁北": 406.571}
    anchor = datetime(2026, 6, 13)
    first = _section("神池南", "宁武西", "23:40:00", "23:55:00")
    second = _section("宁武西", "肃宁北Ⅱ场", "00:05:00", "06:00:00")
    second = {**second, **{key: value.replace("2026-06-13", "2026-06-14") for key, value in second.items() if key.endswith("time")}}
    rows = _trip_rows([first, second], "H001", positions, anchor)
    check("起站发车、终站到达分别取区间两端，跨日站停独立记录",
          [row[4:7] for row in rows] == [
              ("23:40:00", "23:40:00", "origin"),
              ("23:55:00", "24:05:00", "stop"),
              ("30:00:00", "30:00:00", "terminal"),
          ])
    for bad in (
        {**second, "start_station": "神池南"},
        {**second, "starttime": first["starttime"]},
        {**second, "endtime": second["starttime"]},
    ):
        try:
            _trip_rows([first, bad], "H001", positions, anchor)
        except ValueError:
            pass
        else:
            check("断链、重叠或零秒原始区间应被拒绝", False)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "timetable.xlsx"
        zero = rows[1][:4] + (rows[0][5],) + rows[1][5:]
        write_workbook([rows[0], zero, rows[2]], {"heavy": 1, "empty": 0}, path)
        report = load_canonical_timetable(path).validation_report
        check("输入校验拒绝有里程的零秒运行区间",
              not report.is_valid and any(issue.code == "zero_duration_running_section" for issue in report.errors))

def test_real_day_monotonic() -> None:
    if not TELEMETRY.exists():
        print(f"[SKIP] 缺少 {TELEMETRY.name}")
        return
    trips = load_trips()
    positions = station_positions()
    rows, counts = build_day("2026-06-13", trips, positions)
    check("该日重车趟数在 40—80 之间", 40 <= counts["heavy"] <= 80, f"实际 {counts['heavy']}")
    check("该日空车趟数在 40—80 之间", 40 <= counts["empty"] <= 80, f"实际 {counts['empty']}")

    by_train: dict[str, list] = {}
    for row in rows:
        by_train.setdefault(row[0], []).append(row)
    bad_time = 0
    bad_km = 0
    bad_station = 0
    for train_id, items in by_train.items():
        if len(items) < 15:
            bad_station += 1
        previous = None
        for item in items:
            if item[5] < item[4] or (previous is not None and item[4] <= previous[5]):
                bad_time += 1
            if previous is not None and (
                (item[3] - previous[3]) * (1 if train_id.startswith("H") else -1) <= 0
            ):
                bad_km += 1
            previous = item
    check("每趟至少 15 个站", bad_station == 0, f"{bad_station} 趟站数不足")
    check("所有跨站运行时间为正且站停时间非负", bad_time == 0, f"{bad_time} 处异常")
    check("重空里程分别严格递增和递减", bad_km == 0, f"{bad_km} 处异常")

    heavy = by_train.get("H001", [])
    if heavy:
        check("重车终到站是肃宁北", heavy[-1][2] == "肃宁北", f"实际 {heavy[-1][2]}")
        check(
            "重车里程从 0 递增到肃宁北",
            heavy[0][3] == 0.0 and heavy[-1][3] > 400.0,
            f"{heavy[0][3]} → {heavy[-1][3]}",
        )


def main() -> int:
    test_station_resolution()
    test_cross_midnight_format()
    test_yard_move_dropped()
    test_arrival_departure_and_rejection()
    test_classify_requires_full_trip()
    test_real_day_monotonic()
    if failures:
        print(f"\n实测运行图重建：FAIL（{len(failures)} 项）")
        return 1
    print("\n实测运行图重建：PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
