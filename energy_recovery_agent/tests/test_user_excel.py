from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.snapshots import record_from_bytes
from database.user_excel import (
    ExcelConversionError,
    convert_excel_files,
    export_version_tables,
    identify_workbook,
    sheet_storage_paths,
    tables_to_overlays,
    write_templates,
)
from openpyxl import load_workbook


class UserExcelTests(unittest.TestCase):
    def test_identify_chinese_filename(self) -> None:
        self.assertEqual(identify_workbook("列车参数.xlsx").code, "trains")
        self.assertEqual(identify_workbook("运行图.xlsx").code, "timetable")

    def test_unknown_workbook(self) -> None:
        with self.assertRaisesRegex(ExcelConversionError, "无法识别"):
            identify_workbook("随机文件.xlsx")

    def test_empty_workbook_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            with self.assertRaisesRegex(ExcelConversionError, "没有有效数据行"):
                convert_excel_files([root / "列车参数.xlsx"], {})

    def test_train_sheet_converts_and_rejects_unit_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            path = root / "列车参数.xlsx"
            book = load_workbook(path)
            sheet = book["列车"]
            sheet.append(["Heavy", 21600, 5600, 6200, 1.06, 8, 0.1, 0.0028, 2.6, 20, "正向", 0.22, 1, 28800, "", "", "", ""])
            book.save(path)
            overlays = convert_excel_files([path], {})
            self.assertIn("trains.csv", overlays)
            text = overlays["trains.csv"].decode("utf-8")
            self.assertIn("Heavy", text)
            self.assertIn("forward", text)

            sheet["B2"] = "21600 t"
            book.save(path)
            with self.assertRaisesRegex(ExcelConversionError, "不是数字"):
                convert_excel_files([path], {})

    def test_geometry_overlays_only_filled_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            path = root / "线路几何.xlsx"
            book = load_workbook(path)
            book["车站"].append(["S1", "神池南", 0])
            book["车站"].append(["S2", "黄骅港", 583.003])
            book.save(path)
            baseline = {
                "route_metadata.json": b'{"route":{"total_length_km":583.003}}',
                "stations.csv": "station_id,name,position_km\nold,old,1\n".encode("utf-8"),
                "segments.csv": b"segment_id,start_km,end_km\nA,0,1\n",
            }
            overlays = convert_excel_files([path], baseline)
            self.assertIn("stations.csv", overlays)
            self.assertNotIn("segments.csv", overlays)
            self.assertNotIn("route_metadata.json", overlays)
            self.assertIn("黄骅港", overlays["stations.csv"].decode("utf-8"))

    def test_timetable_keeps_uploaded_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            source = root / "运行图.xlsx"
            book = load_workbook(source)
            book["列车"].append(["T1", "重车", "正向", "神池南", "黄骅港", 21600, "", "", 1])
            book["时刻表"].append(["T1", 1, "神池南", 0, "00:00:00", "00:05:00", "origin", "", "", ""])
            renamed = root / "三月运行图.xlsx"
            book.save(renamed)
            overlays = convert_excel_files([renamed], {})
            self.assertEqual(set(overlays), {"platform/三月运行图.xlsx"})

    def test_identify_timetable_by_sheet_when_filename_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            source = root / "运行图.xlsx"
            book = load_workbook(source)
            book["列车"].append(["T1", "空车", "反向", "黄骅港", "神池南", 4320, "", "", 1])
            book["时刻表"].append(["T1", 1, "黄骅港", 583, "01:00:00", "01:05:00", "origin", "", "", ""])
            custom = root / "自定义计划.xlsx"
            book.save(custom)
            overlays = convert_excel_files([custom], {})
            self.assertEqual(set(overlays), {"platform/自定义计划.xlsx"})

    def test_geometry_and_train_tables_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            geometry = root / "线路几何.xlsx"
            book = load_workbook(geometry)
            book["线路参数"].append([583.003, 80, 10, 40, "hybrid"])
            book["车站"].append(["S1", "神池南", 0])
            book["车站"].append(["S2", "黄骅港", 583.003])
            book["区间"].append(["A", 0, 100, -2, 800, "plain", 80])
            book.save(geometry)
            trains = root / "列车参数.xlsx"
            book = load_workbook(trains)
            book["列车"].append(["Heavy", 21600, 5600, 6200, 1.06, 8, 0.1, 0.0028, 2.6, 20, "正向", 0.22, 1, 28800, "", "", "", ""])
            book.save(trains)
            baseline = convert_excel_files([geometry, trains], {})
            records = [record_from_bytes(path, content) for path, content in baseline.items()]
            exported_geometry = export_version_tables(records, "geometry")
            exported_trains = export_version_tables(records, "trains")
            station_names = [row["车站名称"] for row in exported_geometry["sheets"][1]["rows"]]
            self.assertEqual(station_names, ["神池南", "黄骅港"])
            self.assertEqual(exported_trains["sheets"][0]["rows"][0]["方向"], "正向")
            geometry_back = tables_to_overlays("geometry", exported_geometry["sheets"], baseline)
            trains_back = tables_to_overlays("trains", exported_trains["sheets"], baseline)
            self.assertIn("神池南", geometry_back["stations.csv"].decode("utf-8"))
            self.assertIn("黄骅港", geometry_back["stations.csv"].decode("utf-8"))
            self.assertIn("forward", trains_back["trains.csv"].decode("utf-8"))
            self.assertIn("Heavy", trains_back["trains.csv"].decode("utf-8"))

    def test_export_one_sheet_omits_the_rest(self) -> None:
        route = '{"schema_version":"1.0","route":{"total_length_km":583.003}}'.encode("utf-8")
        records = [record_from_bytes("线路参数.json", route)]
        exported = export_version_tables(records, "geometry", "线路参数")
        self.assertEqual([item["name"] for item in exported["sheets"]], ["线路参数"])
        self.assertEqual(exported["sheets"][0]["rows"][0]["线路总长km"], "583.003")
        with self.assertRaisesRegex(ExcelConversionError, "未知工作表"):
            export_version_tables(records, "geometry", "不存在")

    def test_sheet_storage_paths_map_to_chinese_files(self) -> None:
        self.assertEqual(sheet_storage_paths("geometry", "线路参数"), ("线路参数.json",))
        self.assertEqual(sheet_storage_paths("geometry", "区间"), ("区间.csv",))
        self.assertIsNone(sheet_storage_paths("timetable", "时刻表"))
        with self.assertRaisesRegex(ExcelConversionError, "没有工作表"):
            sheet_storage_paths("geometry", "不存在")

    def test_partial_geometry_save_keeps_unopened_sheets(self) -> None:
        baseline = {
            "route_metadata.json": '{"schema_version":"1.0","route":{"total_length_km":583.003}}'.encode("utf-8"),
            "stations.csv": "station_id,name,position_km\nS1,神池南,0\n".encode("utf-8"),
            "segments.csv": "segment_id,start_km,end_km\nA,0,1\n".encode("utf-8"),
        }
        overlays = tables_to_overlays("geometry", [{
            "name": "线路参数",
            "rows": [{
                "线路总长km": "100",
                "最高速度kmh": "80",
                "长大下坡起点km": "10",
                "长大下坡终点km": "40",
                "信号模式": "hybrid",
            }],
        }], baseline)
        self.assertIn("route_metadata.json", overlays)
        self.assertNotIn("stations.csv", overlays)
        self.assertNotIn("segments.csv", overlays)
        self.assertIn("100", overlays["route_metadata.json"].decode("utf-8"))

    def test_overlapping_segments_are_rejected_with_excel_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            write_templates(root)
            path = root / "线路几何.xlsx"
            book = load_workbook(path)
            sheet = book["区间"]
            sheet.append(["A", 0, 10])
            sheet.append(["B", 10, 20])
            book.save(path)
            overlays = convert_excel_files([path], {})
            self.assertIn("segments.csv", overlays)

            sheet.append(["C", 5, 15])
            book.save(path)
            with self.assertRaises(ExcelConversionError) as caught:
                convert_excel_files([path], {})
            message = str(caught.exception)
            self.assertIn("线路几何.xlsx / 区间 / 第4行", message)
            self.assertIn("第2行", message)
            self.assertIn("重叠", message)
            self.assertIn("这一版没有发布", message)

    def test_online_save_does_not_run_upload_conflict_gate(self) -> None:
        overlays = tables_to_overlays("geometry", [{
            "name": "区间",
            "rows": [
                {"区间编号": "A", "起点km": "0", "终点km": "10"},
                {"区间编号": "B", "起点km": "5", "终点km": "12"},
            ],
        }], {})
        self.assertIn("segments.csv", overlays)

    def test_timetable_storage_path_sanitizes_name(self) -> None:
        from database.user_excel import timetable_storage_path

        self.assertEqual(timetable_storage_path("运行图.xlsx"), "platform/运行图.xlsx")
        self.assertEqual(timetable_storage_path("a/b.xlsx"), "platform/b.xlsx")


if __name__ == "__main__":
    unittest.main()
