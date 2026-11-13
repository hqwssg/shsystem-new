# 模块功能说明：验证规模夹具、稳定性汇总和复现门禁的核心行为。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from timetable_input import load_canonical_timetable
from tools.algorithm_scale_stability_benchmark import build_scaled_timetable_fixture, summarize_runs


def _row(target: str, case_type: str, scale: int, seed: int, digest: str) -> dict[str, object]:
    """生成稳定性汇总测试所需的最小成功记录。"""
    return {
        "target": target, "case_type": case_type, "scale": scale, "seed": seed,
        "passed": True, "feasible": True, "wall_time_s": 1.0 + scale / 10,
        "peak_rss_mb": 100.0 + scale, "grid_kwh": 1000.0 + seed / 100,
        "wasted_kwh": 200.0, "effective_regen_loss_kwh": 220.0,
        "total_cost": 800.0, "semantic_sha256": digest,
    }


def main() -> int:
    """覆盖规模输入扩展、通过结论以及同种子不一致阻断。"""
    with TemporaryDirectory(prefix="scale_stability_") as temp_name:
        fixture = build_scaled_timetable_fixture(
            ROOT / "data_templates" / "running_diagram_template.xlsx",
            Path(temp_name) / "scaled",
            scale=2,
            shift_s=7200,
        )
        timetable = load_canonical_timetable(fixture)
        assert timetable.validation_report.is_valid, timetable.validation_report.summary()
        assert len(timetable.trains) == 4
        assert len({train.train_id for train in timetable.trains}) == 4

    rows = []
    for target in ("timetable", "dispatch"):
        rows.extend([_row(target, "scale", 1, 11, "scale1"), _row(target, "scale", 2, 11, "scale2")])
        rows.extend([_row(target, "seed", 2, 11, "seed11"), _row(target, "seed", 2, 23, "seed23")])
        rows.extend([_row(target, "replay", 2, 11, "same"), _row(target, "replay", 2, 11, "same")])
    passed = summarize_runs(rows, ("timetable", "dispatch"), min_seed_feasible_rate=0.8, max_seed_objective_cv=0.25)
    assert passed["accepted"], passed

    rows[-1]["semantic_sha256"] = "different"
    failed = summarize_runs(rows, ("timetable", "dispatch"), min_seed_feasible_rate=0.8, max_seed_objective_cv=0.25)
    assert not failed["accepted"]
    assert "dispatch_same_seed_reproducible" in failed["failed_checks"]
    print("algorithm scale and stability benchmark smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
