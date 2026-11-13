"""Smoke checks for run-level reproducibility manifests."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from run_manifest import create_run_manifest, finalize_run_manifest


class Args:
    """类 Args：执行该模块中的相关处理逻辑。"""
    command = "validate-data"
    data_dir = Path("data")
    source_dir = Path("source")
    timetable = Path("timetable.xlsx")
    output_root = Path("outputs")
    seed = 123
    func = None


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory(prefix="run_manifest_smoke_") as temp:
        root = Path(temp)
        (root / "data").mkdir()
        (root / "source").mkdir()
        (root / "data" / "route_metadata.json").write_text(
            json.dumps(
                {
                    "data_status": "mixed_test_data",
                    "route": {"total_length_km": 12.5},
                    "source_metadata": {
                        "explicit_assumptions": ["test assumption"],
                        "needs_confirmation": ["test confirmation"],
                    },
                }
            ),
            encoding="utf-8",
        )
        (root / "data" / "trains.csv").write_text("id,mass\nT1,1\n", encoding="utf-8")
        (root / "source" / "source.csv").write_text("value\n1\n", encoding="utf-8")
        (root / "timetable.xlsx").write_bytes(b"fixture")
        output_root = root / "outputs"
        args = Args()
        args.output_root = Path("outputs")
        args.seed = 123

        context = create_run_manifest(args, ["validate-data", "--data-dir", "data"], project_root=root)
        manifest_path = context["manifest_path"]
        initial = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if initial["status"] != "running":
            raise AssertionError("manifest must be written before command execution")
        if initial["schema_version"] != "1.1":
            raise AssertionError("manifest schema version was not upgraded")
        if not initial.get("arguments_sha256"):
            raise AssertionError("stable argument hash was not recorded")
        if initial.get("random_seeds", {}).get("seed") != 123:
            raise AssertionError("explicit random seed was not extracted")
        if "dependencies" not in initial.get("environment", {}):
            raise AssertionError("environment dependency versions were not recorded")
        if initial["input_inventory"]["hash_algorithm"] != "sha256":
            raise AssertionError("input hash algorithm was not recorded")
        input_paths = {entry["path"] for entry in initial["input_inventory"]["files"]}
        if "data/trains.csv" not in input_paths or "source/source.csv" not in input_paths:
            raise AssertionError(f"input files missing from manifest: {input_paths}")
        if initial["data_status"][0]["data_status"] != "mixed_test_data":
            raise AssertionError("data status was not captured")
        if initial["code_version"]["code_snapshot_sha256"] == "":
            raise AssertionError("code snapshot hash was not recorded")

        validation_dir = output_root / "data_quality_validation"
        validation_dir.mkdir(parents=True)
        (validation_dir / "data_quality_summary.json").write_text(
            json.dumps({"valid": True, "error_count": 0, "warning_count": 2}), encoding="utf-8"
        )
        (output_root / "new_result.json").write_text('{"ok": true}\n', encoding="utf-8")
        final_path = finalize_run_manifest(context, args, return_code=0)
        final = json.loads(final_path.read_text(encoding="utf-8"))
        if final["status"] != "success" or final["return_code"] != 0:
            raise AssertionError("successful command status was not finalized")
        if final["validation_status"]["status"] != "available":
            raise AssertionError("validation summary was not detected")
        if final["validation_status"]["data_quality"][0]["warning_count"] != 2:
            raise AssertionError("validation summary fields were not preserved")
        output_files = {entry["path"] for entry in final["output_inventory"]["files"]}
        if "outputs/new_result.json" not in output_files:
            raise AssertionError(f"new output was not captured: {output_files}")
        if not final["output_inventory"]["snapshot_sha256"]:
            raise AssertionError("output snapshot hash was not recorded")
        if not final["duration_s"] >= 0:
            raise AssertionError("manifest duration must be non-negative")

    print("run manifest smoke: PASS")


if __name__ == "__main__":
    main()
