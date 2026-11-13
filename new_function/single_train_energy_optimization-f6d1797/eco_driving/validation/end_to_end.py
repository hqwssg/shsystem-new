"""速度曲线 → 再生回收 → baseline/optimized 对比。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from regenerative_braking.simulation.controllers import FixedDutyController, RegenController, ZeroDutyController
from regenerative_braking.simulation.closed_loop import build_closed_loop_controller
from regenerative_braking.simulation.regenerative_simulator import SimulationConfig
from regenerative_braking.simulation.scenario_runner import ComponentBundle, load_component_bundle

from ..integration.regenerative_interface import RegenerativeEvaluation, evaluate_regenerative_recovery
from ..models import EcoDrivingResult
from .comparison import compare


@dataclass(frozen=True)
class EndToEndComparison:
    baseline_eco: EcoDrivingResult
    optimized_eco: EcoDrivingResult
    baseline_regenerative: RegenerativeEvaluation
    optimized_regenerative: RegenerativeEvaluation
    eco_comparison: Mapping[str, object]
    regenerative_comparison: Mapping[str, object]
    controller_name: str
    controller_audit: Mapping[str, object]
    disclaimer: str = "仿真结果，不作为工程结论"

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "eco_comparison": self.eco_comparison,
            "regenerative_comparison": self.regenerative_comparison,
            "baseline_regenerative_metrics": self.baseline_regenerative.metrics,
            "optimized_regenerative_metrics": self.optimized_regenerative.metrics,
            "controller_name": self.controller_name,
            "controller_audit": self.controller_audit,
            "disclaimer": self.disclaimer,
        }


def run_end_to_end_comparison(
    baseline: EcoDrivingResult,
    optimized: EcoDrivingResult,
    *,
    bundle: Optional[ComponentBundle] = None,
    controller: Optional[RegenController] = None,
    config: Optional[SimulationConfig] = None,
    start_km: float = 0.0,
    controller_profile: str = "main",
) -> EndToEndComparison:
    """用同一再生制动控制器评估两条速度曲线。

    未显式传入控制器时默认使用 RHONN + EKF/UKF + NSMC 闭环；
    ``fixed_duty`` / ``zero_duty`` 仅作为显式 baseline。两条曲线始终共享同一
    bundle、控制器和仿真配置，确保比较只反映运行曲线差异。
    """

    bundle = bundle or load_component_bundle()
    simulation_config = config or SimulationConfig(dt=1e-4, record_stride=1)
    if controller is None:
        if controller_profile == "main":
            controller = build_closed_loop_controller(
                limits=bundle.converter_params.duty_limits,
                converter_params=bundle.converter_params,
                storage_params=bundle.storage_params,
                sample_time_s=simulation_config.dt,
            )
        elif controller_profile == "fixed_duty":
            controller = FixedDutyController(0.85, 0.0, bundle.converter_params.duty_limits)
        elif controller_profile == "zero_duty":
            controller = ZeroDutyController(bundle.converter_params.duty_limits)
        else:
            raise ValueError("controller_profile 必须是 main、fixed_duty 或 zero_duty")
    baseline_regen = evaluate_regenerative_recovery(
        baseline, bundle=bundle, controller=controller, config=simulation_config, start_km=start_km,
        scenario_id="eco_baseline_regenerative",
    )
    optimized_regen = evaluate_regenerative_recovery(
        optimized, bundle=bundle, controller=controller, config=simulation_config, start_km=start_km,
        scenario_id="eco_optimized_regenerative",
    )
    comparison_feasible = bool(
        baseline.metadata.get("feasible_candidate", baseline.metadata.get("reached_end", True))
        and optimized.metadata.get("feasible_candidate", optimized.metadata.get("reached_end", True))
    )
    return EndToEndComparison(
        baseline_eco=baseline,
        optimized_eco=optimized,
        baseline_regenerative=baseline_regen,
        optimized_regenerative=optimized_regen,
        eco_comparison=compare(baseline, optimized),
        regenerative_comparison={
            "comparison_feasible": comparison_feasible,
            "baseline": dict(baseline_regen.metrics),
            "optimized": dict(optimized_regen.metrics),
            "captured_energy_delta_kwh": (
                optimized_regen.metrics["captured_regenerative_energy_kwh"]
                - baseline_regen.metrics["captured_regenerative_energy_kwh"]
            ) if comparison_feasible else None,
            "soc_end_delta": (
                optimized_regen.metrics["soc_end"] - baseline_regen.metrics["soc_end"]
                if comparison_feasible else None
            ),
        },
        controller_name=str(getattr(controller, "name", controller.__class__.__name__)),
        controller_audit=(controller.audit() if hasattr(controller, "audit") else {"controller_profile": controller_profile}),
    )
