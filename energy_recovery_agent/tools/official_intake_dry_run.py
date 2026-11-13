# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import argparse
import json
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INBOX = ROOT / "data" / "official_inbox"
DEFAULT_TEMPLATES = ROOT / "data_templates" / "official_intake"
DEFAULT_STATUS = ROOT / "docs" / "official_data_intake_status.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "official_intake_dry_run"


REQUIRED_CATEGORIES = (
    "timetable",
    "vehicle_dynamics",
    "power_arm_electrical",
    "storage",
    "signaling",
    "inventory",
)

TEMPLATE_FILES = {
    "vehicle_dynamics": "vehicle_dynamics_intake.xlsx",
    "power_arm_electrical": "power_arm_electrical_intake.xlsx",
    "storage": "storage_intake.xlsx",
    "signaling": "signaling_blocks_intake.xlsx",
    "inventory": "initial_inventory_intake.xlsx",
}


def _resolve(path: Path) -> Path:
    """函数 _resolve：执行该模块中的相关处理逻辑。"""
    path = Path(path)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _rel(path: Path) -> str:
    """函数 _rel：执行该模块中的相关处理逻辑。"""
    path = _resolve(path)
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _list_files(path: Path) -> List[str]:
    """函数 _list_files：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return []
    files = [p for p in path.rglob("*") if p.is_file() and p.name.lower() != "readme.md"]
    return sorted(str(p.relative_to(path)).replace("\\", "/") for p in files)


def run_dry_run(
    inbox_dir: Path = DEFAULT_INBOX,
    template_dir: Path = DEFAULT_TEMPLATES,
    status_json: Path = DEFAULT_STATUS,
) -> Dict[str, Any]:
    """函数 run_dry_run：执行该模块中的相关处理逻辑。"""
    inbox_dir = _resolve(inbox_dir)
    template_dir = _resolve(template_dir)
    status_json = _resolve(status_json)

    categories: Dict[str, Any] = {}
    missing_categories: List[str] = []
    ready_categories: List[str] = []

    for category in REQUIRED_CATEGORIES:
        cat_dir = inbox_dir / category
        files = _list_files(cat_dir)
        if category == "timetable":
            template_path = ROOT / "data_templates" / "running_diagram_template.xlsx"
        else:
            template_name = TEMPLATE_FILES.get(category)
            template_path = (template_dir / template_name) if template_name else None
        template_exists = bool(template_path and template_path.exists())
        status = "ready_for_adapter" if files else "waiting_for_official_file"
        if files:
            ready_categories.append(category)
        else:
            missing_categories.append(category)
        categories[category] = {
            "inbox_dir": _rel(cat_dir),
            "file_count": len(files),
            "files": files,
            "template": None if template_path is None else _rel(template_path),
            "template_exists": template_exists,
            "status": status,
        }

    experimental: Dict[str, Any] = {}
    if status_json.exists():
        try:
            experimental = json.loads(status_json.read_text(encoding="utf-8")).get(
                "current_experimental_calibration", {}
            )
        except Exception:
            experimental = {}

    report = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inbox_dir": _rel(inbox_dir),
        "template_dir": _rel(template_dir),
        "categories": categories,
        "summary": {
            "required_category_count": len(REQUIRED_CATEGORIES),
            "ready_category_count": len(ready_categories),
            "missing_category_count": len(missing_categories),
            "ready_categories": ready_categories,
            "missing_categories": missing_categories,
            "dry_run_result": "pass_empty_inbox_ready" if not ready_categories else "partial_files_present",
        },
        "algorithm_scope_locks": {
            "mainline_only_stations": 33,
            "exclude_off_mainline_stations": True,
            "ss4_match_policy": "compare_single_meter_and_A_plus_B_pick_best",
            "fit_policy": "fit_core_only_aggregated_ab_exclude_zero_energy_short_stop_low_intensity_single_meter",
            "empty_mass_policy": "multi_tier_no_single_fixed_value_default_4320",
        },
        "current_experimental_calibration": experimental,
        "next_actions": [
            "Drop official files into data/official_inbox/<category>/",
            "Convert reviewed algorithm-facing tables into data/source/ with English names",
            "Rebuild data/real_shuohuang/ and run validate-data + calibrate-energy + simulate",
        ],
    }
    return report


def write_report(report: Dict[str, Any], output_dir: Path) -> Path:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    output_dir = _resolve(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "official_intake_dry_run_summary.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# Official Intake Dry-Run",
        "",
        f"- generated_at_utc: `{report['generated_at_utc']}`",
        f"- dry_run_result: `{report['summary']['dry_run_result']}`",
        f"- ready: {report['summary']['ready_category_count']} / {report['summary']['required_category_count']}",
        f"- missing: `{', '.join(report['summary']['missing_categories']) or 'none'}`",
        "",
        "## Categories",
    ]
    for name, item in report["categories"].items():
        md.append(
            f"- `{name}`: status=`{item['status']}`, files={item['file_count']}, template_exists={item['template_exists']}"
        )
    md.extend(
        [
            "",
            "## Algorithm Scope Locks",
            f"- mainline stations: `{report['algorithm_scope_locks']['mainline_only_stations']}`",
            f"- SS4 policy: `{report['algorithm_scope_locks']['ss4_match_policy']}`",
            f"- fit policy: `{report['algorithm_scope_locks']['fit_policy']}`",
            f"- empty mass policy: `{report['algorithm_scope_locks']['empty_mass_policy']}`",
            "",
        ]
    )
    (output_dir / "official_intake_dry_run_summary.md").write_text("\n".join(md), encoding="utf-8")
    return path


def update_status_json(report: Dict[str, Any], status_json: Path = DEFAULT_STATUS) -> None:
    """函数 update_status_json：执行该模块中的相关处理逻辑。"""
    status_json = _resolve(status_json)
    current: Dict[str, Any] = {}
    if status_json.exists():
        try:
            current = json.loads(status_json.read_text(encoding="utf-8"))
        except Exception:
            current = {}

    current["schema_version"] = "1.0"
    current["goal_items"] = current.get("goal_items", {})
    key_map = {
        "timetable": "official_timetable",
        "vehicle_dynamics": "official_vehicle_dynamics",
        "power_arm_electrical": "official_power_arm_electrical",
        "storage": "official_storage_params",
        "signaling": "official_signaling_blocks",
        "inventory": "official_initial_inventory",
    }
    for category in REQUIRED_CATEGORIES:
        key = key_map[category]
        current["goal_items"][key] = (
            "received_pending_adapter" if category in report["summary"]["ready_categories"] else "missing"
        )
    current["goal_items"]["nonzero_calibration_samples"] = "done_experimental"
    current["goal_items"]["usable_group_coefficients"] = "done_experimental"
    current["goal_items"]["official_intake_dry_run"] = "done"
    current["goal_items"]["formal_energy_saving_or_capacity_conclusions"] = "blocked_until_official_data"
    current["required_inbox"] = list(REQUIRED_CATEGORIES)
    current["algorithm_scope_locks"] = report["algorithm_scope_locks"]
    current["official_intake_dry_run"] = {
        "generated_at_utc": report["generated_at_utc"],
        "result": report["summary"]["dry_run_result"],
        "ready_categories": report["summary"]["ready_categories"],
        "missing_categories": report["summary"]["missing_categories"],
    }

    summary_path = ROOT / "outputs" / "energy_calibration_mainline_refined" / "05_error_analysis_fitcore" / "energy_calibration_error_analysis_summary.json"
    factors_path = ROOT / "data" / "real_shuohuang" / "energy_calibration_factors.json"
    experimental = current.get("current_experimental_calibration", {})
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        experimental.update(
            {
                "sample_count": summary.get("total_rows"),
                "robust_fit_sample_count": summary.get("robust_fit_sample_count"),
                "stratum_counts": summary.get("stratum_counts"),
                "fit_policy": summary.get("fit_policy"),
                "group_median_abs_pct_error": summary.get("group_scaled_median_abs_pct_error_after_scale"),
                "robust_median_abs_pct_error_after_scale": summary.get("robust_median_abs_pct_error_after_scale"),
                "enabled_by_default": False,
                "data_status": "experimental_kwh_calibration",
                "selection_policy": "mainline_mapped_nonzero_traction_from_ab_aggregation",
            }
        )
    if factors_path.exists():
        factors = json.loads(factors_path.read_text(encoding="utf-8"))
        experimental["global_scale"] = factors.get("global", {}).get("traction_scale")
        experimental["enabled_by_default"] = factors.get("enabled_by_default", False)
        experimental["data_status"] = factors.get("data_status", experimental.get("data_status"))
    current["current_experimental_calibration"] = experimental
    current["empty_mass_policy"] = {
        "single_fixed_value_found": False,
        "default_tons": 4320,
        "tiers_tons": [2160, 2668, 3036, 4320],
        "source": "train_formation_modes_2025 + PDF formation totals; no unique empty mass in PDF",
        "pdf_password_note": "PDF opens with Seldom (capital S); lowercase seldom fails",
    }
    status_json.parent.mkdir(parents=True, exist_ok=True)
    status_json.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Dry-run official data inbox readiness without replacing runtime data.")
    parser.add_argument("--inbox-dir", type=Path, default=DEFAULT_INBOX)
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATES)
    parser.add_argument("--status-json", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--update-status", action="store_true", help="Refresh docs/official_data_intake_status.json")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    report = run_dry_run(args.inbox_dir, args.template_dir, args.status_json)
    path = write_report(report, args.output_dir)
    if args.update_status:
        update_status_json(report, args.status_json)
    print(json.dumps({"output": str(path), **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
