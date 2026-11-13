# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.official_data_readiness_pipeline import compare_results, run_pipeline
from tools.official_data_auto_trigger import create_delivery_marker, process_delivery_once


def _verify_auto_trigger(temp_root: Path) -> None:
    """验证到件标记、快照、幂等、篡改阻断和正式门禁状态传递。"""
    package = temp_root / "official_package"
    runtime = package / "converted_runtime"
    source = package / "source"
    runtime.mkdir(parents=True)
    source.mkdir(parents=True)
    (runtime / "route_metadata.json").write_text('{"data_status":"official"}', encoding="utf-8")
    (source / "source_note.txt").write_text("official source", encoding="utf-8")
    (package / "timetable.xlsx").write_bytes(b"test timetable")
    trigger_output = temp_root / "trigger_output"
    waiting = process_delivery_once(package, trigger_output)
    assert waiting["status"] == "waiting", waiting
    assert waiting["processed"] is False
    create_delivery_marker(
        package,
        delivery_id="delivery_20260909_01",
        data_dir="converted_runtime",
        source_dir="source",
        timetable="timetable.xlsx",
        window_id="2026-09-09",
        experiment={"seeds": [11], "settlement_steps_s": [1]},
    )
    calls = []

    def completed_suite(**kwargs: object) -> dict:
        calls.append(kwargs)
        output_root = Path(kwargs["output_root"])
        output_root.mkdir(parents=True)
        return {"status": "completed", "readiness": {"accepted": True}}

    def accepted_project(*_: object, **__: object) -> dict:
        return {
            "accepted": True,
            "simulation": {"returncode": 0, "audit": {"accepted": True}},
        }

    completed = process_delivery_once(
        package, trigger_output, suite_runner=completed_suite, readiness_runner=accepted_project
    )
    assert completed["status"] == "completed", completed
    assert completed["processed"] is True
    assert len(calls) == 1
    snapshot = Path(completed["snapshot_dir"])
    assert (snapshot / "OFFICIAL_DATA_READY.json").is_file()
    assert Path(calls[0]["data_dir"]).resolve() == (snapshot / "converted_runtime").resolve()

    duplicate = process_delivery_once(
        package, trigger_output, suite_runner=completed_suite, readiness_runner=accepted_project
    )
    assert duplicate["status"] == "duplicate", duplicate
    assert duplicate["previous_status"] == "completed"
    assert len(calls) == 1, "相同到件不得重复启动长耗时实验"

    (runtime / "route_metadata.json").write_text('{"data_status":"tampered"}', encoding="utf-8")
    invalid = process_delivery_once(
        package, trigger_output, suite_runner=completed_suite, readiness_runner=accepted_project
    )
    assert invalid["status"] == "invalid", invalid
    assert "SHA-256" in invalid["message"]
    assert len(calls) == 1

    # 修复载荷并生成新版本标记，确认验收阻断状态也会落入账本且不自动重试。
    (runtime / "route_metadata.json").write_text('{"data_status":"official"}', encoding="utf-8")
    create_delivery_marker(
        package,
        delivery_id="delivery_20260909_02",
        data_dir="converted_runtime",
        source_dir="source",
        timetable="timetable.xlsx",
        window_id="2026-09-09",
    )

    def blocked_project(*_: object, **__: object) -> dict:
        return {"accepted": False, "simulation": None}

    blocked = process_delivery_once(package, trigger_output, readiness_runner=blocked_project)
    assert blocked["status"] == "blocked", blocked
    assert blocked["formal_data_accepted"] is False

    create_delivery_marker(
        package,
        delivery_id="delivery_20260909_03",
        data_dir="converted_runtime",
        source_dir="source",
        timetable="timetable.xlsx",
        window_id="2026-09-09",
    )
    suite_call_count = 0

    def unexpected_suite(**_: object) -> dict:
        nonlocal suite_call_count
        suite_call_count += 1
        return {"status": "completed", "readiness": {"accepted": True}}

    def failed_project(*_: object, **__: object) -> dict:
        return {"accepted": True, "simulation": {"returncode": 1, "audit": {"accepted": False}}}

    failed = process_delivery_once(
        package,
        trigger_output,
        suite_runner=unexpected_suite,
        readiness_runner=failed_project,
    )
    assert failed["status"] == "failed", failed
    assert failed["project_validation_accepted"] is True
    assert failed["project_simulation_passed"] is False
    assert suite_call_count == 0, "工程仿真或质量审计失败后不得进入正式对比总控"

    create_delivery_marker(
        package,
        delivery_id="delivery_20260909_04",
        data_dir="converted_runtime",
        source_dir="source",
        timetable="timetable.xlsx",
        window_id="2026-09-09",
    )
    lock_path = trigger_output / ".official_data_trigger.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    busy = process_delivery_once(package, trigger_output, readiness_runner=accepted_project)
    assert busy["status"] == "busy", busy
    lock_path.unlink()
    assert (trigger_output / "trigger_state.json").is_file()
    assert (trigger_output / "latest_trigger_summary.json").is_file()


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    if "--trigger-only" in sys.argv[1:]:
        with tempfile.TemporaryDirectory() as tmp:
            _verify_auto_trigger(Path(tmp))
        print("official data auto trigger branches: PASS")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "readiness"
        data = ROOT / "data" / "real_shuohuang"
        before = sorted(p.name for p in data.iterdir())
        result = run_pipeline(data, ROOT / "data" / "source", ROOT / "data_templates" / "running_diagram_template.xlsx", out)
        assert result["accepted"] is False, "当前虚拟/未确认数据应被正式门禁阻断"
        assert (out / "candidate_manifest.json").is_file()
        assert (out / "readiness_summary.json").is_file()
        assert sorted(p.name for p in data.iterdir()) == before, "只读流水线不得修改输入目录"
        left = Path(tmp) / "left"; right = Path(tmp) / "right"
        left.mkdir(); right.mkdir()
        (left / "summary.json").write_text(json.dumps({"total_gen_kwh": 1}), encoding="utf-8")
        (right / "summary.json").write_text(json.dumps({"total_gen_kwh": 2}), encoding="utf-8")
        diff = compare_results(left, right)
        assert diff["changed_count"] == 1
        cli_out = Path(tmp) / "cli"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "run_project.py"), "official-data-readiness",
             "--data-dir", str(data), "--source-dir", str(ROOT / "data" / "source"),
             "--timetable", str(ROOT / "data_templates" / "running_diagram_template.xlsx"),
             "--output-dir", str(cli_out)],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert proc.returncode == 1, "统一入口必须阻断未验收的当前数据"
        assert (cli_out / "readiness_summary.json").is_file()
        _verify_auto_trigger(Path(tmp))
    print("official data readiness smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
