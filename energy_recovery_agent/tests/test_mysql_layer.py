from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.mysql import _parse_mysql_url
from database.parameters import validate_run_parameters


class MysqlLayerTests(unittest.TestCase):
    def test_parse_mysql_url(self) -> None:
        parsed = _parse_mysql_url("mysql://root:secret@127.0.0.1:3306/carbon_emissions")
        self.assertEqual(parsed["host"], "127.0.0.1")
        self.assertEqual(parsed["port"], 3306)
        self.assertEqual(parsed["user"], "root")
        self.assertEqual(parsed["password"], "secret")
        self.assertEqual(parsed["database"], "carbon_emissions")

    def test_unknown_parameter_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_run_parameters("dispatch", {"not_a_real_field": 1})

    def test_timetable_audit_requires_path(self) -> None:
        with self.assertRaises(ValueError):
            validate_run_parameters("timetable_audit", {})
        validate_run_parameters("timetable_audit", {"timetable_relative_path": "timetable.csv"})

    def test_worker_once_parser_accepts_run_id(self) -> None:
        from database.cli import build_parser

        args = build_parser().parse_args(["worker-once", "--run-id", "11111111-1111-1111-1111-111111111111"])
        self.assertEqual(args.run_id, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(args.command, "worker-once")

    def test_delete_run_parser_requires_run_id(self) -> None:
        from database.cli import build_parser

        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["delete-run"])
        args = parser.parse_args(["delete-run", "--run-id", "11111111-1111-1111-1111-111111111111"])
        self.assertEqual(args.command, "delete-run")
        self.assertEqual(args.run_id, "11111111-1111-1111-1111-111111111111")

    def test_import_excel_parser(self) -> None:
        from database.cli import build_parser

        args = build_parser().parse_args([
            "import-excel",
            "--excel-dir", "tmp",
            "--base-project-code", "shuohuang_demo",
            "--base-version-code", "v1",
            "--project-code", "shuohuang_demo",
            "--project-name", "朔黄演示",
            "--route-name", "shuohuang",
            "--version-code", "v2",
        ])
        self.assertEqual(args.command, "import-excel")
        self.assertEqual(args.base_version_code, "v1")
        self.assertEqual(args.version_code, "v2")

    def test_delete_missing_run_reports_error(self) -> None:
        import os
        from uuid import UUID
        from database.mysql import SimulationRepository, connect_mysql

        url = os.environ.get("ENERGY_DATABASE_URL")
        if not url:
            self.skipTest("Set ENERGY_DATABASE_URL to an isolated test database for MySQL integration tests")
        connection = connect_mysql(url)
        try:
            repository = SimulationRepository(connection)
            with self.assertRaisesRegex(ValueError, "任务不存在"):
                repository.delete_run(UUID("00000000-0000-0000-0000-000000000000"))
        finally:
            connection.close()

    def test_rolling_mutex(self) -> None:
        with self.assertRaises(ValueError):
            validate_run_parameters(
                "rolling_rescheduling",
                {
                    "disturbance_history_relative_path": "replay.json",
                    "storage_devices": [{"storage_section_id": "s1", "soc_kwh": 1}],
                },
            )

    def test_format_energy_time_array_and_string(self) -> None:
        def pad(value: object) -> str:
            return str(value).zfill(2)

        def format_energy_time(value):
            if value is None or value == "":
                return "-"
            if isinstance(value, (list, tuple)) and len(value) >= 3:
                y, m, d = value[0], value[1] if len(value) > 1 else 1, value[2] if len(value) > 2 else 1
                h = value[3] if len(value) > 3 else 0
                i = value[4] if len(value) > 4 else 0
                s = value[5] if len(value) > 5 else 0
                return f"{y}-{pad(m)}-{pad(d)} {pad(h)}:{pad(i)}:{pad(s)}"
            if isinstance(value, str) and len(value) >= 19 and value[4] == "-":
                return value.replace("T", " ")[:19]
            return str(value)

        self.assertEqual(format_energy_time(None), "-")
        self.assertEqual(format_energy_time([2026, 9, 17, 16, 39, 34]), "2026-09-17 16:39:34")
        self.assertEqual(format_energy_time("2026-09-17 16:39:34"), "2026-09-17 16:39:34")


if __name__ == "__main__":
    unittest.main()
