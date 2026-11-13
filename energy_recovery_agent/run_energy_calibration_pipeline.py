# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence
import argparse
import hashlib
import json
import shutil

from energy_calibration_alignment import build_alignment
from energy_calibration_error_analyzer import analyze_energy_errors
from energy_calibration_factor_builder import build_factor_config
from energy_calibration_quality import audit_calibration_quality, write_quality_outputs
from energy_calibration_sensitivity import run_sensitivity
from smart_meter_calibration_builder import build_calibration_samples
from smart_meter_match_analyzer import analyze_matches
from smart_meter_time_matcher import match_smart_meter_time_windows, write_match_outputs


DEFAULT_SMART_METER_DIR = Path("data") / "source" / "smart_meter"
DEFAULT_DATA_DIR = Path("data") / "real_shuohuang"
DEFAULT_OUTPUT_DIR = Path("outputs") / "energy_calibration_pipeline"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """函数 write_json：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_if_exists(source: Path, target: Path) -> None:
    """函数 copy_if_exists：执行该模块中的相关处理逻辑。"""
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _file_fingerprint(path: Path) -> dict[str, Any]:
    """记录校准输入文件的大小和 SHA-256，支持后续复现与审计。"""
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _input_manifest(
    smart_meter_dir: Path,
    data_dir: Path,
    validation_alignment_csv: Optional[Path] = None,
) -> dict[str, Any]:
    """生成校准链路实际读取目录的文件指纹清单。"""
    files = []
    for root, role in ((Path(smart_meter_dir), "smart_meter"), (Path(data_dir), "model_data")):
        if root.is_dir():
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                files.append({"role": role, **_file_fingerprint(path)})
    if validation_alignment_csv is not None:
        validation_path = Path(validation_alignment_csv)
        if not validation_path.is_file():
            raise FileNotFoundError(f"外部验证对齐表不存在：{validation_path}")
        files.append({"role": "external_validation_alignment", **_file_fingerprint(validation_path)})
    return {"schema_version": "1.0", "files": files}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    def fmt_pct(value: Any) -> str:
        """函数 fmt_pct：执行该模块中的相关处理逻辑。"""
        return "N/A" if value is None else f"{float(value):.3f}%"

    def fmt_float(value: Any) -> str:
        """函数 fmt_float：执行该模块中的相关处理逻辑。"""
        return "N/A" if value is None else f"{float(value):.6f}"

    lines = [
        "# 模型结果—电表数据校准流水线报告",
        "",
        "Pipeline status: " + str(summary.get("status", "unknown")),
        "Usable calibration result: " + str(summary.get("valid", False)),
        "Publication status: " + str(summary.get("publication_status", "not_requested")),
        "本报告由 `run_energy_calibration_pipeline.py` 自动生成。",
        "",
        "## 输入",
        "",
        f"- 智能电表目录：`{summary['inputs']['smart_meter_dir']}`",
        f"- 真实数据目录：`{summary['inputs']['data_dir']}`",
        f"- 外部验证对齐表：`{summary['inputs']['validation_alignment_csv'] or '未提供，使用确定性分层留出验证'}`",
        "",
        "## 关键结果",
        "",
        f"- 时间窗口匹配记录数：{summary['time_matching']['match_count']}",
        f"- 高可信校准候选数：{summary['match_analysis']['candidate_count']}",
        f"- mismatch 数：{summary['match_analysis']['mismatch_count']}",
        f"- 校准样本数：{summary['calibration_samples']['sample_count']}",
        f"- 样本选择策略：{summary['calibration_samples'].get('selection_policy', 'all_usable_candidates')}",
        f"- 覆盖实时电表 trainid 数：{summary['calibration_samples'].get('covered_realtime_trainid_count', 0)}",
        f"- 可对齐样本数：{summary['alignment_none']['alignment_status_counts'].get('aligned', 0)}",
        f"- 鲁棒拟合样本数：{summary['error_analysis']['robust_fit_sample_count']}",
        f"- 建议全局牵引系数：{fmt_float(summary['error_analysis']['suggested_global_traction_scale'])}",
        f"- 独立留出验证样本数：{summary['quality_audit']['validation_sample_count']}",
        f"- 验证策略：`{summary['quality_audit']['validation_strategy']}`",
        f"- 校准质量门禁：{summary['quality_audit']['accepted']}",
        f"- 质量门禁未通过项：{', '.join(summary['quality_audit']['failed_checks']) or '无'}",
        "",
        "## 三种口径对比",
        "",
        "| 口径 | 中位绝对百分误差 | 平均绝对百分误差 |",
        "| --- | ---: | ---: |",
        f"| 未校准 | {fmt_pct(summary['sensitivity']['uncalibrated_median_abs_pct_error'])} | {fmt_pct(summary['sensitivity']['uncalibrated_mean_abs_pct_error'])} |",
        f"| 全局系数 | {fmt_pct(summary['sensitivity']['global_median_abs_pct_error'])} | {fmt_pct(summary['sensitivity']['global_mean_abs_pct_error'])} |",
        f"| 分组系数 | {fmt_pct(summary['sensitivity']['group_median_abs_pct_error'])} | {fmt_pct(summary['sensitivity']['group_mean_abs_pct_error'])} |",
        "",
        "## 输出目录",
        "",
    ]
    for name, value in summary["outputs"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 电表能量单位已根据《需要确认的问题（列车电表）(1)》答复确认为 kWh。",
            "- 默认 `--overlap-policy exclude`：涉及 station 时间重叠的区间会被排除，剩余干净区间继续用于校准样本构建。",
            "- 默认只匹配与 SS4 实时覆盖时间窗重叠的区间；可用 `--no-restrict-to-realtime-coverage` 关闭。",
            "- 匹配器会自动比较单表与 `58A+58B` / `151A+151B` 聚合候选，优先选择能量更一致的结果。",
            "- 若启用 `--representative-samples`，样本表优先保证不同 realtime trainid 覆盖，重复样本不全部纳入。",
            "- 校准系数默认不启用，只用于对比和敏感性测试。",
            "- `valid=true` 现在表示独立留出验证和发布质量门禁均通过，而不仅是存在样本。",
            "- 分组系数目前主要由 58A+58B、151A+151B 聚合样本支撑，不能直接视为全线最终工程系数。",
            "- 0 能耗记录可能对应调车、未升弓或统计数据问题，当前只作为复核样本，不作为普通牵引校准样本。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")

def run_pipeline(
    *,
    smart_meter_dir: Path,
    data_dir: Path,
    output_dir: Path,
    boundary_tolerance_s: float,
    energy_tolerance: float,
    max_interval_rows_per_file: Optional[int],
    max_realtime_rows_per_file: Optional[int],
    overlap_policy: str,
    representative_samples: bool,
    max_per_realtime_trainid: int,
    publish_calibration: bool = False,
    restrict_to_realtime_coverage: bool = True,
    mainline_only: bool = True,
    min_fit_samples: int = 30,
    min_validation_samples: int = 10,
    validation_fraction: float = 0.20,
    validation_model: str = "grouped",
    max_median_ape_pct: float = 30.0,
    max_p90_ape_pct: float = 60.0,
    max_wape_pct: float = 30.0,
    min_scale: float = 0.2,
    max_scale: float = 5.0,
    validation_alignment_csv: Optional[Path] = None,
) -> dict[str, Any]:
    """函数 run_pipeline：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    input_manifest = _input_manifest(smart_meter_dir, data_dir, validation_alignment_csv)
    write_json(output_dir / "calibration_input_manifest.json", input_manifest)

    step1_dir = output_dir / "01_time_matching"
    rows = match_smart_meter_time_windows(
        smart_meter_dir,
        boundary_tolerance_s=boundary_tolerance_s,
        energy_tolerance=energy_tolerance,
        max_interval_rows_per_file=max_interval_rows_per_file,
        max_realtime_rows_per_file=max_realtime_rows_per_file,
        overlap_policy=overlap_policy,
        restrict_to_realtime_coverage=restrict_to_realtime_coverage,
    )
    write_match_outputs(rows, step1_dir)
    time_matching_summary = json.loads((step1_dir / "smart_meter_time_window_matching_summary.json").read_text(encoding="utf-8"))

    step2_dir = output_dir / "02_match_analysis"
    match_analysis_summary = analyze_matches(step1_dir / "smart_meter_time_window_matches.csv", step2_dir)

    step3_dir = output_dir / "03_calibration_samples"
    data_sample_csv = step3_dir / "smart_meter_calibration_samples.csv"
    station_csv = data_dir / "stations.csv"
    sample_summary = build_calibration_samples(
        step2_dir / "smart_meter_calibration_candidates.csv",
        data_sample_csv,
        representative=representative_samples,
        max_per_realtime_trainid=max_per_realtime_trainid,
        station_csv=station_csv,
        mainline_only=mainline_only,
    )
    step4_dir = output_dir / "04_alignment_none"
    alignment_none_summary = build_alignment(
        data_sample_csv,
        station_csv,
        step4_dir,
        energy_calibration_mode="none",
        infrastructure_data_dir=data_dir,
    )

    step5_dir = output_dir / "05_error_analysis"
    error_summary = analyze_energy_errors(step4_dir / "arc_energy_vs_meter_samples.csv", step5_dir)

    step6_quality_dir = output_dir / "06_quality_audit"
    quality_summary = audit_calibration_quality(
        step4_dir / "arc_energy_vs_meter_samples.csv",
        validation_alignment_csv=validation_alignment_csv,
        min_fit_samples=min_fit_samples,
        min_validation_samples=min_validation_samples,
        validation_fraction=validation_fraction,
        validation_model=validation_model,
        max_median_ape_pct=max_median_ape_pct,
        max_p90_ape_pct=max_p90_ape_pct,
        max_wape_pct=max_wape_pct,
        min_scale=min_scale,
        max_scale=max_scale,
    )
    write_quality_outputs(quality_summary, step6_quality_dir)

    step7_dir = output_dir / "07_factor_config"
    step8_global_dir = output_dir / "08_alignment_global"
    step9_grouped_dir = output_dir / "09_alignment_grouped"
    step10_dir = output_dir / "10_sensitivity"
    data_factor_json = step7_dir / "energy_calibration_factors.json"
    has_calibration_samples = sample_summary["sample_count"] > 0
    quality_passed = bool(quality_summary["accepted"])
    if quality_passed:
        factor_config = build_factor_config(
            step5_dir / "energy_calibration_group_coefficients.csv",
            step5_dir / "energy_calibration_error_analysis_summary.json",
            data_factor_json,
            sample_source=data_sample_csv,
            quality_summary_json=step6_quality_dir / "calibration_quality_summary.json",
        )
        alignment_global_summary = build_alignment(
            data_sample_csv,
            station_csv,
            step8_global_dir,
            energy_calibration_mode="global",
            factor_json=data_factor_json,
            infrastructure_data_dir=data_dir,
        )
        alignment_grouped_summary = build_alignment(
            data_sample_csv,
            station_csv,
            step9_grouped_dir,
            energy_calibration_mode="grouped",
            factor_json=data_factor_json,
            infrastructure_data_dir=data_dir,
        )
        sensitivity_summary = run_sensitivity(
            step4_dir / "arc_energy_vs_meter_samples.csv",
            data_factor_json,
            step10_dir,
        )
    else:
        if data_factor_json.exists():
            data_factor_json.unlink()
        factor_config = {
            "enabled_by_default": False,
            "global": {"traction_scale": None},
        }
        skipped = {
            "status": "skipped_quality_gate_failed",
            "reason": "校准样本未通过独立留出验证和发布质量门禁。",
        }
        alignment_global_summary = dict(skipped)
        alignment_grouped_summary = dict(skipped)
        sensitivity_summary = {
            **skipped,
            "uncalibrated_median_abs_pct_error": None,
            "uncalibrated_mean_abs_pct_error": None,
            "global_median_abs_pct_error": None,
            "global_mean_abs_pct_error": None,
            "group_median_abs_pct_error": None,
            "group_mean_abs_pct_error": None,
        }

    publication_status = "not_requested"
    if publish_calibration and quality_passed:
        publish_sample = data_dir / "smart_meter_calibration_samples.csv"
        publish_sample_summary = data_dir / "smart_meter_calibration_samples_summary.json"
        publish_factor = data_dir / "energy_calibration_factors.json"
        copy_if_exists(data_sample_csv, publish_sample)
        copy_if_exists(
            data_sample_csv.with_name(data_sample_csv.stem + "_summary.json"),
            publish_sample_summary,
        )
        copy_if_exists(data_factor_json, publish_factor)
        publication_status = "published"
    elif publish_calibration:
        publication_status = "blocked_quality_gate_failed"

    summary = {
        "pipeline_completed": True,
        "valid": quality_passed,
        "publication_ready": quality_passed,
        "status": (
            "completed_quality_passed"
            if quality_passed
            else "incomplete_no_calibration_samples"
            if not has_calibration_samples
            else "completed_quality_blocked"
        ),
        "publication_status": publication_status,
        "inputs": {
            "smart_meter_dir": str(smart_meter_dir),
            "data_dir": str(data_dir),
            "validation_alignment_csv": str(validation_alignment_csv or ""),
            "boundary_tolerance_s": boundary_tolerance_s,
            "energy_tolerance": energy_tolerance,
            "max_interval_rows_per_file": max_interval_rows_per_file,
            "max_realtime_rows_per_file": max_realtime_rows_per_file,
            "overlap_policy": overlap_policy,
            "restrict_to_realtime_coverage": restrict_to_realtime_coverage,
            "mainline_only": mainline_only,
            "representative_samples": representative_samples,
            "max_per_realtime_trainid": max_per_realtime_trainid,
            "publish_calibration": publish_calibration,
            "quality_thresholds": quality_summary["thresholds"],
        },
        "time_matching": time_matching_summary,
        "match_analysis": match_analysis_summary,
        "calibration_samples": sample_summary,
        "alignment_none": alignment_none_summary,
        "error_analysis": error_summary,
        "quality_audit": quality_summary,
        "factor_config": {
            "status": "generated" if quality_passed else "skipped_quality_gate_failed",
            "output_json": str(data_factor_json) if quality_passed else "",
            "enabled_by_default": factor_config["enabled_by_default"],
            "global_scale": factor_config["global"]["traction_scale"],
        },
        "alignment_global": alignment_global_summary,
        "alignment_grouped": alignment_grouped_summary,
        "sensitivity": sensitivity_summary,
        "outputs": {
            "time_matching": str(step1_dir),
            "match_analysis": str(step2_dir),
            "calibration_samples": str(step3_dir),
            "alignment_none": str(step4_dir),
            "error_analysis": str(step5_dir),
            "quality_audit": str(step6_quality_dir),
            "factor_config": str(step7_dir) if quality_passed else "",
            "alignment_global": str(step8_global_dir) if quality_passed else "",
            "alignment_grouped": str(step9_grouped_dir) if quality_passed else "",
            "sensitivity": str(step10_dir) if quality_passed else "",
            "input_manifest": str(output_dir / "calibration_input_manifest.json"),
            "pipeline_summary": str(output_dir / "pipeline_summary.json"),
            "pipeline_report": str(output_dir / "PIPELINE_REPORT.md"),
            "published_sample": str(data_dir / "smart_meter_calibration_samples.csv") if publication_status == "published" else "",
            "published_factor_config": str(data_dir / "energy_calibration_factors.json") if publication_status == "published" else "",
        },
    }
    write_json(output_dir / "pipeline_summary.json", summary)
    write_report(output_dir / "PIPELINE_REPORT.md", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Run the full smart-meter energy calibration pipeline.")
    parser.add_argument("--smart-meter-dir", type=Path, default=DEFAULT_SMART_METER_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--boundary-tolerance-s", type=float, default=300.0)
    parser.add_argument("--energy-tolerance", type=float, default=1.0)
    parser.add_argument("--max-interval-rows-per-file", type=int)
    parser.add_argument("--max-realtime-rows-per-file", type=int)
    parser.add_argument(
        "--overlap-policy",
        choices=("strict", "exclude"),
        default="exclude",
        help="strict rejects overlapping station intervals; exclude drops overlapped station rows and continues. Default exclude is recommended because station files contain many overlaps.",
    )
    parser.add_argument(
        "--no-restrict-to-realtime-coverage",
        action="store_true",
        help="Match intervals outside SS4 realtime coverage windows as well.",
    )
    parser.add_argument(
        "--no-mainline-only",
        action="store_true",
        help="Keep off-mainline or zero-distance meter samples; default keeps only mainline-mapped nonzero traction samples.",
    )
    parser.add_argument("--representative-samples", action="store_true", help="Build compact representative calibration samples by realtime trainid.")
    parser.add_argument("--max-per-realtime-trainid", type=int, default=20)
    parser.add_argument("--min-fit-samples", type=int, default=30)
    parser.add_argument("--min-validation-samples", type=int, default=10)
    parser.add_argument("--validation-fraction", type=float, default=0.20)
    parser.add_argument(
        "--validation-model",
        choices=("global", "grouped"),
        default="grouped",
        help="Predeclared calibration model evaluated by the quality gate; grouped falls back to global for unsupported groups.",
    )
    parser.add_argument(
        "--validation-alignment-csv",
        type=Path,
        help="Optional aligned samples from another date/source batch for independent out-of-sample validation.",
    )
    parser.add_argument("--max-median-ape-pct", type=float, default=30.0)
    parser.add_argument("--max-p90-ape-pct", type=float, default=60.0)
    parser.add_argument("--max-wape-pct", type=float, default=30.0)
    parser.add_argument("--min-scale", type=float, default=0.2)
    parser.add_argument("--max-scale", type=float, default=5.0)
    parser.add_argument(
        "--publish-calibration",
        action="store_true",
        help="Explicitly publish non-empty calibration samples and factors into data-dir.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    args = build_parser().parse_args(argv)
    summary = run_pipeline(
        smart_meter_dir=args.smart_meter_dir,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        boundary_tolerance_s=args.boundary_tolerance_s,
        energy_tolerance=args.energy_tolerance,
        max_interval_rows_per_file=args.max_interval_rows_per_file,
        max_realtime_rows_per_file=args.max_realtime_rows_per_file,
        overlap_policy=args.overlap_policy,
        representative_samples=args.representative_samples,
        max_per_realtime_trainid=args.max_per_realtime_trainid,
        publish_calibration=args.publish_calibration,
        restrict_to_realtime_coverage=not args.no_restrict_to_realtime_coverage,
        mainline_only=not args.no_mainline_only,
        min_fit_samples=args.min_fit_samples,
        min_validation_samples=args.min_validation_samples,
        validation_fraction=args.validation_fraction,
        validation_model=args.validation_model,
        validation_alignment_csv=args.validation_alignment_csv,
        max_median_ape_pct=args.max_median_ape_pct,
        max_p90_ape_pct=args.max_p90_ape_pct,
        max_wape_pct=args.max_wape_pct,
        min_scale=args.min_scale,
        max_scale=args.max_scale,
    )
    print(json.dumps(
        {
            "output_dir": str(args.output_dir),
            "match_count": summary["time_matching"]["match_count"],
            "candidate_count": summary["match_analysis"]["candidate_count"],
            "sample_count": summary["calibration_samples"]["sample_count"],
            "group_median_abs_pct_error": summary["sensitivity"]["group_median_abs_pct_error"],
            "report": str(args.output_dir / "PIPELINE_REPORT.md"),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if summary.get("valid", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
