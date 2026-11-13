"""验证联合参数区间合同、场景设计和参数缩放。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from joint_parameter_robustness import (
    apply_battery_factors,
    apply_electrical_factors,
    apply_train_factors,
    build_joint_parameter_scenarios,
    load_joint_range_config,
)
from run_dispatch_case import load_case_inputs


def main() -> None:
    config = load_joint_range_config(ROOT / "data_templates" / "joint_parameter_ranges_template.json")
    scenarios_a = build_joint_parameter_scenarios(config)
    scenarios_b = build_joint_parameter_scenarios(config)
    assert scenarios_a == scenarios_b
    assert scenarios_a[0].design_role == "nominal"
    assert {item.design_role for item in scenarios_a} >= {
        "directed_adverse_corner", "directed_favorable_corner",
        "all_lower_corner", "all_upper_corner", "latin_hypercube_interior",
    }
    assert len(scenarios_a) == 39

    with TemporaryDirectory(prefix="joint_smoke_") as temp_name:
        case = load_case_inputs(ROOT / "data" / "real_shuohuang", Path(temp_name))
        adverse = next(item for item in scenarios_a if item.design_role == "directed_adverse_corner")
        trains = apply_train_factors(case.trains, adverse.factors)
        battery = apply_battery_factors(case.battery, adverse.factors)
        limits = apply_electrical_factors(case.power_arm_limits, adverse.factors)
        assert trains["Heavy"].mass_tons > case.trains["Heavy"].mass_tons
        assert trains["Heavy"].max_traction_kN < case.trains["Heavy"].max_traction_kN
        assert battery.capacity_kwh < case.battery.capacity_kwh
        first_key = next(iter(limits))
        assert limits[first_key].max_traction_supply_kw < case.power_arm_limits[first_key].max_traction_supply_kw
    print("joint parameter robustness smoke: PASS")


if __name__ == "__main__":
    main()
