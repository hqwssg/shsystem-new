from __future__ import annotations

import unittest

from database.file_names import (
    records_to_algorithm_names,
    records_to_storage_names,
    to_algorithm_path,
    to_storage_path,
)
from database.snapshots import record_from_bytes


class FileNameMappingTests(unittest.TestCase):
    def test_round_trip_known_files(self) -> None:
        self.assertEqual(to_storage_path("trains.csv"), "列车参数.csv")
        self.assertEqual(to_algorithm_path("列车参数.csv"), "trains.csv")
        self.assertEqual(to_storage_path("platform/running_diagram.xlsx"), "platform/运行图.xlsx")
        self.assertEqual(to_algorithm_path("platform/运行图.xlsx"), "platform/running_diagram.xlsx")

    def test_custom_timetable_keeps_uploaded_name(self) -> None:
        self.assertEqual(to_storage_path("platform/三月运行图.xlsx"), "platform/三月运行图.xlsx")
        self.assertEqual(to_algorithm_path("platform/三月运行图.xlsx"), "platform/三月运行图.xlsx")

    def test_already_chinese_or_english_stays_stable(self) -> None:
        self.assertEqual(to_storage_path("列车参数.csv"), "列车参数.csv")
        self.assertEqual(to_algorithm_path("trains.csv"), "trains.csv")

    def test_storage_records_last_write_wins_on_collision(self) -> None:
        first = record_from_bytes("platform/running_diagram.xlsx", b"old")
        second = record_from_bytes("platform/运行图.xlsx", b"new")
        stored = records_to_storage_names((first, second))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].relative_path, "platform/运行图.xlsx")
        self.assertEqual(stored[0].content, b"new")

    def test_algorithm_records_restore_english_names(self) -> None:
        stored = record_from_bytes("列车参数.csv", b"heavy,empty")
        restored = records_to_algorithm_names((stored,))
        self.assertEqual(restored[0].relative_path, "trains.csv")
        self.assertEqual(restored[0].content, b"heavy,empty")


if __name__ == "__main__":
    unittest.main()
