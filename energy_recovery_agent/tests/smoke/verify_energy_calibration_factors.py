# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_calibration_factor_builder import build_factor_config
from energy_calibration_error_analyzer import analyze_energy_errors
from energy_calibration_factors import load_energy_calibration_config, resolve_energy_calibration_factor
from formation_modes import load_formation_modes
from _calibration_success_fixture import write_nonzero_alignment_fixture
from smoke_paths import smoke_output


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_dir = smoke_output("energy_calibration_factor_builder_smoke")
    alignment_csv = write_nonzero_alignment_fixture(output_dir / "fixture" / "arc_energy_vs_meter_samples.csv")
    analysis_dir = output_dir / "analysis"
    analyze_energy_errors(alignment_csv, analysis_dir)
    group_csv = analysis_dir / "energy_calibration_group_coefficients.csv"
    summary_json = analysis_dir / "energy_calibration_error_analysis_summary.json"
    output_json = output_dir / "energy_calibration_factors.json"
    config = build_factor_config(group_csv, summary_json, output_json)
    if config["enabled_by_default"]:
        raise AssertionError("Calibration factors should not be enabled by default.")
    loaded = load_energy_calibration_config(output_json)
    down = resolve_energy_calibration_factor(travel_direction="down", aggregation_type="aggregated_ab", config=loaded)
    up = resolve_energy_calibration_factor(travel_direction="up", aggregation_type="aggregated_ab", config=loaded)
    fallback = resolve_energy_calibration_factor(travel_direction="unknown", aggregation_type="single_meter", config=loaded)
    if down.traction_scale <= 0 or up.traction_scale <= 0 or fallback.traction_scale <= 0:
        raise AssertionError("Expected positive traction scales.")
    if down.group_level != "direction_aggregation":
        raise AssertionError("Expected direction_aggregation factor for down aggregated_ab.")
    if up.group_level != "direction_aggregation":
        raise AssertionError("Expected direction_aggregation factor for up aggregated_ab.")
    if abs(down.traction_scale - 1.2) > 1e-9 or abs(up.traction_scale - 0.8) > 1e-9:
        raise AssertionError("Generated direction factors do not match the deterministic fixture.")
    invalid_config = {
        "data_status": "experimental_kwh_calibration",
        "global": {"sample_count": 0, "traction_scale": 1.0},
        "groups": {},
    }
    invalid_factor = resolve_energy_calibration_factor(config=invalid_config)
    if invalid_factor.coefficient_status != "no_calibration_samples":
        raise AssertionError("Zero-sample factor configs must not be treated as usable.")
    for invalid_config in (
        {"global": {"sample_count": 1, "traction_scale": "not-a-number"}},
        {"global": {"sample_count": 1, "traction_scale": -1.0}},
        {"global": {"sample_count": 1, "traction_scale": 1.0}, "enabled_by_default": "flase"},
        {"global": {"sample_count": 1.5, "traction_scale": 1.0}},
        {"global": []},
        {"groups": []},
        {
            "global": {"sample_count": 1, "traction_scale": 1.0},
            "groups": {"travel_direction": []},
        },
        {
            "global": {"sample_count": 1, "traction_scale": 1.0},
            "groups": {"travel_direction": {"down": "bad"}},
        },
        [],
    ):
        try:
            resolve_energy_calibration_factor(config=invalid_config)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid calibration configuration was accepted: {invalid_config!r}")
    invalid_root_path = output_dir / "invalid_root.json"
    invalid_root_path.write_text(json.dumps([]), encoding="utf-8")
    try:
        load_energy_calibration_config(invalid_root_path)
    except ValueError as exc:
        assert "root" in str(exc)
    else:
        raise AssertionError("Non-object calibration JSON root was accepted")
    disabled = resolve_energy_calibration_factor(
        config={
            "global": {"sample_count": 1, "traction_scale": 1.0},
            "enabled_by_default": "false",
        }
    )
    if disabled.enabled_by_default:
        raise AssertionError("String false was incorrectly converted to True")
    invalid_formation_path = output_dir / "invalid_formation_modes.csv"
    with invalid_formation_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("category,load_state,formation_mode,wagon_count,mass_tons\n")
        handle.write("heavy,heavy,1+1,1.5,1000\n")
    try:
        load_formation_modes(invalid_formation_path)
    except ValueError as exc:
        assert "wagon_count" in str(exc)
    else:
        raise AssertionError("Fractional formation wagon_count was silently truncated")
    invalid_group_path = output_dir / "invalid_group_coefficients.csv"
    invalid_summary_path = output_dir / "invalid_summary.json"
    invalid_factor_path = output_dir / "invalid_factor_config.json"
    with invalid_group_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "group_level,group_value,scale_median,sample_count,usable_ratio_count,coefficient_status\n"
        )
        handle.write("travel_direction,down,1.0,1.5,1,usable\n")
    invalid_summary_path.write_text(
        '{"suggested_global_traction_scale": 1.0, "robust_fit_sample_count": 1}',
        encoding="utf-8",
    )
    try:
        build_factor_config(invalid_group_path, invalid_summary_path, invalid_factor_path)
    except ValueError as exc:
        assert "sample_count" in str(exc)
    else:
        raise AssertionError("Fractional calibration sample_count was silently truncated")
    print("energy calibration factors passed")
    print({"down": round(down.traction_scale, 6), "up": round(up.traction_scale, 6), "fallback": round(fallback.traction_scale, 6)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
