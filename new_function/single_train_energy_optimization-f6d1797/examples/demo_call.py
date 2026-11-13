"""最小调用示例：跑平直制动场景，校验链路并导出结果。

运行：python examples/demo_call.py
退出码 0 表示链路正常；非 0 表示环境或数据有问题。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regenerative_braking.io.data_paths import load_project_paths
from regenerative_braking.simulation.closed_loop import (  # noqa: E402
    build_closed_loop_controller,
)
from regenerative_braking.simulation.regenerative_simulator import (  # noqa: E402
    SimulationConfig,
)
from regenerative_braking.simulation.scenario_runner import (  # noqa: E402
    build_simulator,
    load_component_bundle,
)
from regenerative_braking.validation.scenarios import build_validation_scenarios  # noqa: E402

DT = 1e-4
OUTPUT = ROOT / "demo_output"


def main() -> int:
    paths = load_project_paths()
    bundle = load_component_bundle(paths)

    scenario = next(
        item for item in build_validation_scenarios(bundle, DT) if item.scenario_id == "s1_flat_braking"
    )
    controller = build_closed_loop_controller(
        converter_params=bundle.converter_params,
        storage_params=bundle.storage_params,
        sample_time_s=DT,
    )
    result = build_simulator(bundle).run(
        scenario.series,
        controller=controller,
        config=SimulationConfig(dt=DT, record_stride=10),
    )

    ledger = result.ledger.to_dict(kwh=True)
    metrics = result.to_scenario_metrics().to_flat_dict()
    columns = result.arrays.to_columns()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(
            {
                "scenario": scenario.scenario_id,
                "dt_s": DT,
                "controller": "rhonn_nsmc",
                "ledger": ledger,
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    with (OUTPUT / "timeseries.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns.keys())
        writer.writerows(zip(*columns.values()))

    peak_voltage = max(result.arrays.output_voltage_v)
    closure = abs(ledger["closure_residual_kWh"]) / max(ledger["mechanical_braking_energy_kWh"], 1e-9)

    net_kwh = ledger["storage_net_of_grid_import_energy_kWh"]
    gross_kwh = ledger["storage_energy_kWh"]

    print(f"场景          {scenario.scenario_id}（{len(scenario.series)} 拍，dt = {DT:g} s）")
    print(f"共享数据      {bundle.parameter_status.get('shared_rolling_stock')}（real = 已注入电制动曲线）")
    print(f"机械制动能量  {ledger['mechanical_braking_energy_kWh']:.4f} kWh")
    print(f"净再生能量    {net_kwh:.6f} kWh（已扣除电网回吸，比较「回收多少」只看这个）")
    print(f"端口吸收能量  {gross_kwh:.6f} kWh（含从母线回吸的电网电 {gross_kwh - net_kwh:.6f} kWh）")
    print(f"输出峰值电压  {peak_voltage:.3f} V")
    print(f"闭合相对残差  {closure:.3e}")
    print(f"结果已写出    {OUTPUT}")

    problems = []
    if peak_voltage >= 1500.0:
        problems.append(f"输出峰值电压 {peak_voltage:.1f} V 超过 1500 V 上限")
    if closure >= 1e-4:
        problems.append(f"闭合相对残差 {closure:.2e} 超过 1e-4 容差")
    if net_kwh <= 0:
        problems.append("净再生能量非正：储能吸收抵不过电网回吸，控制链可能未生效")

    if problems:
        print("\n链路异常：")
        for item in problems:
            print(f"  - {item}")
        return 1

    print("\n链路自检通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
