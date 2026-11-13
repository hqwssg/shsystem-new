"""验证论文实验跨窗统计链路及其防伪重复口径。"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.paper_experiment_pipeline as pipeline


FIELDS = [
    "scenario_code",
    "algorithm",
    "seed",
    "status",
    "quality_accepted",
    "decision_action",
    "decision_reason",
    "selected_candidate_id",
    "total_traction_kwh",
    "total_regen_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
    "wasted_kwh",
    "grid_kwh",
    "effective_regen_loss_kwh",
    "recovery_rate",
    "issue_count",
    "max_shift_min",
    "total_adjustment_min",
    "delay_min",
    "constraint_violation",
    "runtime_s",
    "grid_saving_vs_baseline_kwh",
    "waste_reduction_vs_baseline_kwh",
    "effective_loss_reduction_vs_baseline_kwh",
    "output_dir",
    "error",
]


def _row(code: str, algorithm: str, grid: float, wasted: float, loss: float, recovery: float, seed: object = "") -> dict:
    """构造一个质量合格的最小正式实验结果行。"""

    return {
        "scenario_code": code,
        "algorithm": algorithm,
        "seed": seed,
        "status": "completed",
        "quality_accepted": True,
        "decision_action": "optimize" if algorithm in {"rule", "nsga2"} else "baseline",
        "decision_reason": "fixture",
        "selected_candidate_id": "fixture",
        "total_traction_kwh": 1200.0,
        "total_regen_kwh": 300.0,
        "battery_charge_kwh": 120.0,
        "battery_discharge_kwh": 100.0,
        "wasted_kwh": wasted,
        "grid_kwh": grid,
        "effective_regen_loss_kwh": loss,
        "recovery_rate": recovery,
        "issue_count": 0,
        "max_shift_min": 0 if algorithm in {"baseline_audit", "no_storage_ablation"} else 5,
        "total_adjustment_min": 0 if algorithm in {"baseline_audit", "no_storage_ablation"} else 10,
        "delay_min": 0,
        "constraint_violation": 0,
        "runtime_s": 1.5 if algorithm in {"baseline_audit", "no_storage_ablation"} else 3.5,
        "grid_saving_vs_baseline_kwh": "",
        "waste_reduction_vs_baseline_kwh": "",
        "effective_loss_reduction_vs_baseline_kwh": "",
        "output_dir": "fixture",
        "error": "",
    }


def _write_window(root: Path, window_id: str, offset: float) -> None:
    """写入三个固定策略和三个 NSGA-II 种子的合成评价窗。"""

    root.mkdir(parents=True)
    rows = [
        _row("F01_B0_baseline", "baseline_audit", 1000 + offset, 200 + offset, 250 + offset, 0.40),
        _row("F02_B1_no_storage", "no_storage_ablation", 1060 + offset, 260 + offset, 310 + offset, 0.25),
        _row("F03_R1_rule", "rule", 980 + offset, 185 + offset, 230 + offset, 0.44),
        _row("F04_NSGA_seed_11", "nsga2", 972 + offset, 181 + offset, 222 + offset, 0.46, 11),
        _row("F04_NSGA_seed_23", "nsga2", 970 + offset, 180 + offset, 220 + offset, 0.47, 23),
        _row("F04_NSGA_seed_37", "nsga2", 968 + offset, 179 + offset, 218 + offset, 0.48, 37),
    ]
    with (root / "formal_experiment_kpi.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema_version": "1.0",
        "status": "completed",
        "window_id": window_id,
        "scenarios": rows,
        "calibration": {
            "provided": True,
            "accepted": True,
            "status": "fixture",
            "summary_path": "fixture_calibration.json",
            "sha256": "fixture_sha256",
            "failed_checks": [],
            "validation_metrics": {"wape_pct": 5.0},
        },
        "timestep_sensitivity": [
            {
                "time_step_s": step,
                "status": "completed",
                "quality_accepted": True,
                "runtime_s": 1.0 / step,
                "grid_kwh": 1000.0 + offset + error,
                "wasted_kwh": 200.0 + offset + error,
                "effective_regen_loss_kwh": 250.0 + offset + error,
                "recovery_rate": 0.4 - error / 10000.0,
                "grid_difference_vs_1s": error,
                "grid_error_pct_vs_1s": error / (1000.0 + offset) * 100.0,
                "wasted_difference_vs_1s": error,
                "wasted_error_pct_vs_1s": error / (200.0 + offset) * 100.0,
                "effective_loss_difference_vs_1s": error,
                "effective_loss_error_pct_vs_1s": error / (250.0 + offset) * 100.0,
                "recovery_rate_difference_vs_1s": -error / 10000.0,
                "error": "",
                "output_dir": "fixture",
            }
            for step, error in ((1, 0.0), (5, 2.0), (10, 5.0))
        ],
    }
    (root / "formal_experiment_summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def _read_csv(path: Path) -> list:
    """读取测试输出 CSV。"""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    """运行四窗统计回归并核验关键论文口径。"""

    retained_root = os.environ.get("PAPER_EXPERIMENT_PIPELINE_SMOKE_OUTPUT_ROOT", "").strip()
    context = nullcontext(retained_root) if retained_root else TemporaryDirectory(prefix="paper_experiment_pipeline_")
    with context as temp_name:
        temp = Path(temp_name)
        temp.mkdir(parents=True, exist_ok=True)
        windows = []
        for index in range(4):
            window_id = f"W{index + 1:02d}"
            result_dir = temp / "source" / window_id
            _write_window(result_dir, window_id, index * 10.0)
            windows.append({"window_id": window_id, "include": True, "exclusion_reason": "", "result_dir": str(result_dir)})
        windows.append({"window_id": "W_EXCLUDED", "include": False, "exclusion_reason": "预先判定该窗缺少完整列车事件"})
        manifest = {
            "schema_version": "1.0",
            "study_id": "paper_statistics_smoke",
            "dataset_version": "synthetic_fixture_v1",
            "experiment_parameters": {"seeds": [11, 23, 37]},
            "analysis": {
                "metrics": ["grid_kwh", "wasted_kwh", "effective_regen_loss_kwh", "recovery_rate"],
                "confidence_level": 0.95,
                "bootstrap_replicates": 300,
                "permutation_replicates": 300,
                "statistics_seed": 99,
                "min_windows_for_inference": 3,
            },
            "windows": windows,
        }
        manifest_path = temp / "study.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        output_root = temp / "output"
        summary = pipeline.run_paper_experiment_pipeline(
            study_manifest=manifest_path,
            output_root=output_root,
            aggregate_only=True,
        )
        assert summary["status"] == "completed", summary
        assert summary["included_window_count"] == 4
        assert summary["completed_window_count"] == 4
        assert summary["statistical_unit"] == "evaluation_window"
        assert summary["exclusion_count"] == 1
        analysis = _read_csv(output_root / "statistics" / "paper_analysis_rows.csv")
        paired = _read_csv(output_root / "statistics" / "paper_paired_effects.csv")
        statistical = _read_csv(output_root / "statistics" / "paper_statistical_summary.csv")
        strategy_summary = _read_csv(output_root / "statistics" / "paper_strategy_summary.csv")
        seeds = _read_csv(output_root / "statistics" / "paper_seed_stability.csv")
        timesteps = _read_csv(output_root / "statistics" / "paper_timestep_sensitivity.csv")
        calibration = _read_csv(output_root / "statistics" / "paper_calibration_evidence.csv")
        assert len(analysis) == 16, "每窗应只有4个策略记录，不能把3个种子当作3个跨窗样本"
        nsga_w1 = next(row for row in analysis if row["window_id"] == "W01" and row["strategy"] == "nsga2")
        assert int(nsga_w1["replicate_count"]) == 3
        assert math.isclose(float(nsga_w1["grid_kwh"]), 970.0)
        effect = next(row for row in paired if row["window_id"] == "W01" and row["strategy"] == "nsga2" and row["metric"] == "grid_kwh")
        assert math.isclose(float(effect["improvement"]), 30.0)
        direct_effect = next(row for row in paired if row["window_id"] == "W01" and row["strategy"] == "nsga2_vs_rule" and row["metric"] == "grid_kwh")
        assert direct_effect["reference_strategy"] == "rule" and direct_effect["treatment_strategy"] == "nsga2"
        assert math.isclose(float(direct_effect["improvement"]), 10.0)
        stat = next(row for row in statistical if row["strategy"] == "nsga2" and row["metric"] == "grid_kwh")
        assert int(stat["n_windows"]) == 4
        assert stat["inference_ready"] == "True"
        assert stat["p_value_raw"] and stat["p_value_holm"]
        assert math.isclose(float(stat["p_value_raw"]), 0.125)
        assert math.isclose(float(stat["p_value_holm"]), 1.0)
        assert len(strategy_summary) == 16
        assert len(paired) == 64 and len(statistical) == 16
        baseline_grid = next(row for row in strategy_summary if row["strategy"] == "baseline" and row["metric"] == "grid_kwh")
        assert math.isclose(float(baseline_grid["median"]), 1015.0)
        assert len(seeds) == 16
        assert len(timesteps) == 12
        assert len(calibration) == 4 and all(row["accepted"] == "True" for row in calibration)
        assert (output_root / "statistics" / "figures" / "paired_effects.png").stat().st_size > 1000
        assert (output_root / "statistics" / "figures" / "nsga2_seed_stability.png").stat().st_size > 1000
        assert (output_root / "statistics" / "figures" / "timestep_sensitivity.png").stat().st_size > 1000
        assert (output_root / "STUDY_FREEZE_MANIFEST.json").is_file()
        assert (output_root / "statistics" / "PAPER_STATISTICS_REPORT.md").is_file()
        assert (output_root / "statistics" / "paper_window_status.csv").is_file()

        repeat_root = temp / "output_repeat"
        repeated = pipeline.run_paper_experiment_pipeline(
            study_manifest=manifest_path,
            output_root=repeat_root,
            aggregate_only=True,
        )
        assert repeated["status"] == "completed"
        assert (output_root / "statistics" / "paper_statistical_summary.csv").read_bytes() == (
            repeat_root / "statistics" / "paper_statistical_summary.csv"
        ).read_bytes(), "同清单统计结果必须逐字节复现"

        duplicate = dict(manifest)
        duplicate["windows"] = [windows[0], dict(windows[0])]
        duplicate_path = temp / "duplicate.json"
        duplicate_path.write_text(json.dumps(duplicate, ensure_ascii=False), encoding="utf-8")
        try:
            pipeline.run_paper_experiment_pipeline(study_manifest=duplicate_path, output_root=temp / "invalid", aggregate_only=True)
        except ValueError as exc:
            assert "重复" in str(exc)
        else:
            raise AssertionError("重复评价窗必须被拒绝")

        seed_mismatch = dict(manifest)
        seed_mismatch["experiment_parameters"] = {"seeds": [11, 23]}
        seed_mismatch["windows"] = windows[:1]
        mismatch_path = temp / "seed_mismatch.json"
        mismatch_path.write_text(json.dumps(seed_mismatch, ensure_ascii=False), encoding="utf-8")
        mismatch_summary = pipeline.run_paper_experiment_pipeline(
            study_manifest=mismatch_path,
            output_root=temp / "seed_mismatch_output",
            aggregate_only=True,
        )
        assert mismatch_summary["status"] == "failed"
        assert mismatch_summary["completed_window_count"] == 0
        assert mismatch_summary["exclusion_count"] == 1

        # 模拟单窗正式总控，验证批量模式确实逐窗执行并随后进入统计。
        input_root = temp / "batch_inputs"
        data_dir = input_root / "runtime"
        source_dir = input_root / "source"
        data_dir.mkdir(parents=True)
        source_dir.mkdir(parents=True)
        timetable = input_root / "timetable.xlsx"
        timetable.write_bytes(b"fixture")
        executed = []
        original_runner = pipeline.run_formal_experiment_suite

        def fake_formal_runner(**kwargs: object) -> dict:
            """用确定性结果替代长耗时单窗算法，隔离验证批量编排。"""

            window_id = str(kwargs["window_id"])
            result_dir = Path(kwargs["output_root"])
            executed.append(window_id)
            _write_window(result_dir, window_id, float(len(executed)))
            return {"status": "completed", "window_id": window_id}

        pipeline.run_formal_experiment_suite = fake_formal_runner
        try:
            batch_manifest = {
                "study_id": "batch_execution_smoke",
                "dataset_version": "synthetic_fixture_v1",
                "experiment_parameters": {"seeds": [11, 23, 37]},
                "analysis": {
                    "metrics": ["grid_kwh", "wasted_kwh"],
                    "bootstrap_replicates": 100,
                    "permutation_replicates": 100,
                    "min_windows_for_inference": 2,
                },
                "windows": [
                    {
                        "window_id": window_id,
                        "include": True,
                        "exclusion_reason": "",
                        "data_dir": str(data_dir),
                        "source_dir": str(source_dir),
                        "timetable": str(timetable),
                    }
                    for window_id in ("B01", "B02")
                ],
            }
            batch_path = temp / "batch_study.json"
            batch_path.write_text(json.dumps(batch_manifest, ensure_ascii=False), encoding="utf-8")
            batch_summary = pipeline.run_paper_experiment_pipeline(
                study_manifest=batch_path,
                output_root=temp / "batch_output",
                aggregate_only=False,
            )
            assert batch_summary["status"] == "completed", batch_summary
            assert executed == ["B01", "B02"]
            assert batch_summary["completed_window_count"] == 2
            assert (temp / "batch_output" / "windows" / "B01" / "formal_experiment_kpi.csv").is_file()
        finally:
            pipeline.run_formal_experiment_suite = original_runner

    print("paper experiment pipeline smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
