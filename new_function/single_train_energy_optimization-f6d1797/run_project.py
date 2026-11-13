"""单列车再生制动能量回收 —— 阶段 1/2 入口（物理底座 + baseline 控制器）。

用法
----
    # 默认：Scenario 1（平直道常规制动）+ Scenario 2（长大下坡） × 6 个 baseline
    python run_project.py

    # 指定步长与场景
    python run_project.py --dt 2e-4 --scenario 1
    python run_project.py --scenario route --route-start-km 108 --route-v0-kmh 70

    # 只打印，不落盘
    python run_project.py --no-write

输出（默认写到 configs/data_paths.yaml 的 experiments_root 下）
---------------------------------------------------------------
    data/experiments/<run_id>/
        summary.json          场景 × baseline 指标表（含数据状态与免责声明）
        summary.csv           同上，扁平表
        timeseries_*.csv      逐步记录（电压/电流/占空比/SOC/功率）
        README.md             本次运行的说明

本入口的范围
------------
**只跑阶段 1 的物理底座与阶段 2 的 baseline 控制器**（开环 3 项 + 闭环 3 项）。
阶段 3–11 的实现各有自己的入口，本文件不重复它们：

    阶段 3–8   RHONN / EKF / UKF / 模式切换 / NSMC / 联合闭环
               → `simulation/closed_loop.py::build_closed_loop_controller`
    阶段 9     场景 × baseline 验证矩阵
               → `python tools/run_validation_suite.py`
    阶段 11    跨项目时间桶导出
               → `python tools/export_cross_project.py`
    诊断       控制律候选对比（方案问题 1 / 14）
               → `python tools/compare_control_law_candidates.py`
    诊断       控制通道诊断（方案问题 15 / 16：B 可辨识性与状态冗余）
               → `python tools/diagnose_control_channel.py`

边界纪律（本项目硬约束）
------------------------
* 只读共享铁路基础数据，绝不写回（写入保护由 io.data_paths.ensure_read_only 兜底）。
* 参数按 `official / real / derived / assumed` 四级标注来源；`assumed` 只用于仿真研究，
  不得当作工程值引用。所有输出一律标注「仿真结果，不作为工程结论」。
* 本入口只跑阶段 1 物理底座与阶段 2 基线控制器，主算法结果不混入对比表。
* 引用任何能量数字必须同时写明**积分步长、控制器装配与能量口径**。

主算法口径
----------
主算法（RHONN 辨识 + EKF/UKF 权重训练 + NSMC）的闭环入口是
`simulation/closed_loop.py::build_closed_loop_controller`，本文件不重复它的结果。
正式读数、适用范围与假设清单见
`docs/技术实现方案-单列车再生制动能量回收-RHONN-EKF-UKF-NSMC.md`，
推导与裁定细节见 `docs/regenerative_braking_algorithm.md`。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from regenerative_braking.identification import PENDING_SCHEME_CONFIRMATION
from regenerative_braking.io.data_loader import (
    DataLoadError,
    load_shared_railway_data,
)
from regenerative_braking.io.data_paths import (
    DataPathError,
    ProjectPaths,
    check_shared_data,
    ensure_read_only,
    load_project_paths,
)
from regenerative_braking.io.output_presentation import glossary_lines
from regenerative_braking.simulation.regenerative_simulator import (
    SimulationArrays,
    SimulationConfig,
    SimulationResult,
)
from regenerative_braking.simulation.scenario_runner import (
    ComponentBundle,
    build_simulator,
    default_baseline_cases,
    load_component_bundle,
    scenario_1_flat_braking,
    scenario_2_long_downhill,
    scenario_route_braking,
)
from regenerative_braking.simulation.profiles import ProfileError, ProfileSeries

RESULT_DISCLAIMER = (
    "仿真结果，不作为工程结论 —— "
    "本输出由离线数字仿真得到，适用范围以参数溯源等级与假设清单为界。"
    "能量、回收率与电压电流峰值不得直接用于线路节能率申报、设备选型或合同考核。"
)


class RunError(RuntimeError):
    """运行配置或装配错误。"""


# ------------------------------------------------------------------
# 场景装配
# ------------------------------------------------------------------


def _build_profiles(
    bundle: ComponentBundle,
    paths: ProjectPaths,
    scenarios: Sequence[str],
    dt: float,
    record_stride: int,
    route_start_km: float,
    route_v0_kmh: float,
) -> List[ProfileSeries]:
    series: List[ProfileSeries] = []

    if "1" in scenarios:
        series.append(scenario_1_flat_braking(bundle, dt=dt))
    if "2" in scenarios:
        series.append(scenario_2_long_downhill(bundle, dt=dt))
    if "route" in scenarios:
        report = check_shared_data(paths)
        missing = [name for name, ok in report.items() if not ok]
        if missing:
            raise RunError(
                "route 场景需要共享铁路基础数据，但缺失：" + ", ".join(missing) + f"\nshared_data_root = {paths.shared_data_root}"
            )
        shared = load_shared_railway_data(paths)
        from regenerative_braking.io.data_loader import find_long_downhill_ranges

        ranges = find_long_downhill_ranges(shared, max_gradient_per_mille=-6.0, min_length_km=1.0)
        series.append(
            scenario_route_braking(
                bundle,
                shared,
                start_km=route_start_km,
                v0_kmh=route_v0_kmh,
                dt=dt,
                max_time_s=60.0,
            )
        )
        if ranges:
            print(f"[线路] 共享真实坡度识别到 {len(ranges)} 个长大下坡区段，示例：{ranges[0][0]:.3f}~{ranges[0][1]:.3f} km")
    return series


# ------------------------------------------------------------------
# 落盘
# ------------------------------------------------------------------


def _write_summary(
    outdir: Path,
    rows: Sequence[Mapping[str, Any]],
    paths: ProjectPaths,
    bundle: ComponentBundle,
    config: SimulationConfig,
) -> Tuple[Path, Path]:
    json_path = outdir / "summary.json"
    csv_path = outdir / "summary.csv"

    payload = {
        "disclaimer": RESULT_DISCLAIMER,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stage": "阶段一物理底座与阶段二基线控制器",
        "entry_point_scope": (
            "本入口只跑阶段一物理底座与阶段二基线控制器；"
            "阶段三至十一各有独立入口，详见其他入口字段。"
        ),
        "not_implemented_yet": [],
        "implemented_stages": [
            "1_physical_baseline",
            "2_baseline_controllers",
            "3_rhonn_identifier",
            "4_ekf_weight_trainer",
            "5_ukf_weight_trainer",
            "6_explainable_mode_selector",
            "7_nsmc",
            "8_joint_closed_loop",
            "9_validation_suite",
            "10_shared_route_data",
            "11_cross_project_export",
        ],
        "other_entry_points": {
            "stage_3_to_8_closed_loop": "simulation/closed_loop.py::build_closed_loop_controller",
            "stage_9_validation_suite": "python tools/run_validation_suite.py",
            "stage_11_cross_project_export": "python tools/export_cross_project.py",
            "control_law_candidates": "python tools/compare_control_law_candidates.py",
            "control_channel_diagnosis": "python tools/diagnose_control_channel.py",
        },
        "main_algorithm_status": (
            "可运行。主算法由 RHONN 辨识、EKF/UKF 权重训练、可解释模式切换与 NSMC 组成，"
            "闭环入口为 simulation/closed_loop.py::build_closed_loop_controller，不在本入口内。"
            "本入口只跑基线控制器，用于提供同口径对照，主算法结果不混入对比表。"
            "主算法读数、适用范围与假设清单见 "
            "docs/技术实现方案-单列车再生制动能量回收-RHONN-EKF-UKF-NSMC.md。"
        ),
        "pending_scheme_confirmation": PENDING_SCHEME_CONFIRMATION,
        "numerics": {"dt": config.dt, "record_stride": config.record_stride, "apply_u0_limit": config.apply_u0_limit},
        "data_paths": {
            "shared_data_root": str(paths.shared_data_root),
            "single_train_data_root": str(paths.single_train_data_root),
            "shared_data_read_only": paths.shared_data_read_only,
        },
        "parameter_data_status": dict(bundle.parameter_status),
        "rows": [dict(row) for row in rows],
    }
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)

    if rows:
        keys: List[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in keys})

    return json_path, csv_path


def _row_keys(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """按实际写出顺序汇总指标表列名，供运行说明逐列给出中文释义。"""
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return keys


def _timeseries_keys() -> list[str]:
    """逐步记录列名取实体真实字段顺序，避免与落盘顺序漂移。"""
    return [field.name for field in fields(SimulationArrays) if field.name != "regen_limit_reason"]


def _write_readme(outdir: Path, profiles: Sequence[ProfileSeries], rows: Sequence[Mapping[str, Any]]) -> Path:
    path = outdir / "README.md"
    lines = [
        "# 运行说明",
        "",
        f"> **{RESULT_DISCLAIMER}**",
        "",
        "## 本入口范围",
        "",
        "阶段 1（物理仿真底座）+ 阶段 2（基线控制器：开环 3 项 + 闭环 3 项）。",
        "",
        "本目录**不含**主算法结果；其他入口如下：",
        "",
        "- 阶段 3–8（RHONN / EKF / UKF / 模式切换 / NSMC / 联合闭环）：",
        "  `simulation/closed_loop.py::build_closed_loop_controller`",
        "- 阶段 9（场景 × 基线验证矩阵）：`python tools/run_validation_suite.py`",
        "- 阶段 11（跨项目时间桶导出）：`python tools/export_cross_project.py`",
        "- 控制律候选对比：`python tools/compare_control_law_candidates.py`",
        "- 控制通道诊断：`python tools/diagnose_control_channel.py`",
        "",
        "## 场景",
        "",
    ]
    for series in profiles:
        lines.append(f"- `{series.scenario_id}`：{series.description}；{series.summary()}")
    lines += [
        "",
        "## 指标表（summary.csv / summary.json）",
        "",
        "每行是一个「场景 × 控制器」组合，数值为本次运行结果；机读键名保持不变，",
        "下表给出中文名与单位：",
        "",
    ]
    if rows:
        lines.append(f"共 {len(rows)} 行（场景 × 控制器）。")
        lines.append("")
    lines.extend(glossary_lines(_row_keys(rows)))
    lines += [
        "",
        "## 逐步记录（timeseries_*.csv）",
        "",
        "按 `record_stride` 抽样的逐步记录，列释义：",
        "",
    ]
    lines.extend(glossary_lines(_timeseries_keys()))
    lines += [
        "",
        "## 口径提醒",
        "",
        "- 能量单位统一为千瓦时，电压为伏、电流为安、功率为瓦、时间为秒。",
        "- `captured_energy_kWh` 是储能端吸收能量，`storage_energy_kWh` 是净存入能量，",
        "  `loss_energy_kWh` 含回网能量——三者口径不同，不可互相替代。",
        "- 引用能量必须同时写明积分步长、控制器装配与能量口径。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="单列车再生制动能量回收 —— 阶段 1/2 可运行入口")
    parser.add_argument("--dt", type=float, default=1e-4, help="仿真步长（s），默认 1e-4")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=["1", "2", "route"],
        help="要运行的场景，可重复；默认 1 和 2",
    )
    parser.add_argument("--record-stride", type=int, default=10, help="逐步记录抽样间隔，默认 10")
    parser.add_argument("--route-start-km", type=float, default=108.0, help="route 场景起点公里标")
    parser.add_argument("--route-v0-kmh", type=float, default=70.0, help="route 场景入口速度 km/h")
    parser.add_argument("--outdir", type=Path, default=None, help="输出目录，默认 experiments_root/<run_id>")
    parser.add_argument("--no-write", action="store_true", help="只打印，不落盘")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    scenarios = args.scenario or ["1", "2"]

    try:
        paths = load_project_paths()
    except DataPathError as exc:
        print(f"[错误] 数据路径配置不可用：{exc}", file=sys.stderr)
        return 2

    print(paths.describe())
    print()

    try:
        bundle = load_component_bundle(paths)
    except DataLoadError as exc:
        print(f"[错误] 参数装配失败：{exc}", file=sys.stderr)
        return 2

    print("参数数据状态（如实标注，未确认字段不得当作工程值）：")
    for name, status in bundle.parameter_status.items():
        print(f"  - {name}: {status}")
    print()

    try:
        profiles = _build_profiles(
            bundle,
            paths,
            scenarios,
            args.dt,
            args.record_stride,
            args.route_start_km,
            args.route_v0_kmh,
        )
    except (RunError, ProfileError) as exc:
        print(f"[错误] 场景构造失败：{exc}", file=sys.stderr)
        return 2

    if not profiles:
        print("[错误] 没有可运行的场景", file=sys.stderr)
        return 2

    config = SimulationConfig(dt=args.dt, record_stride=args.record_stride)

    outdir: Optional[Path] = None
    if not args.no_write:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        outdir = Path(args.outdir) if args.outdir else (paths.experiments_root / run_id)
        outdir = outdir.resolve()
        try:
            ensure_read_only(paths, outdir)
        except DataPathError as exc:
            print(f"[错误] 输出目录被写入保护拒绝：{exc}", file=sys.stderr)
            return 2
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"输出目录：{outdir}")
        print()

    all_rows: List[Dict[str, Any]] = []
    cases = default_baseline_cases(bundle)

    for series in profiles:
        print(f"=== {series.scenario_id} ===")
        print(f"    {series.summary()}")
        for case in cases:
            simulator = build_simulator(bundle)
            result: SimulationResult = simulator.run(series, controller=case.controller, config=config)
            metrics = result.to_scenario_metrics()
            row = metrics.to_flat_dict()
            row["baseline_label"] = case.label
            row["result_kind"] = "simulation_result_not_engineering_conclusion"
            all_rows.append(row)

            ledger = result.ledger
            print(
                f"    [{case.label:<24}] "
                f"机械制动 {ledger.mechanical_braking_energy_j / 3.6e6:9.4f} kWh | "
                f"可再生 {ledger.motor_electrical_energy_j / 3.6e6:9.4f} kWh | "
                f"回收 {ledger.storage_accepted_energy_j / 3.6e6:9.4f} kWh | "
                f"回网 {ledger.grid_export_energy_j / 3.6e6:9.4f} kWh | "
                f"SOC {ledger.soc_start:.4f}→{ledger.soc_end:.4f} | "
                f"闭合残差 {ledger.closure_residual_j / 3.6e6:.3e} kWh"
            )

            if outdir is not None:
                result.to_csv(outdir / f"timeseries_{series.scenario_id}_{case.label}.csv")
        print()

    if all_rows:
        best = max(all_rows, key=lambda r: float(r.get("captured_energy_kWh", 0.0) or 0.0))
        print(
            "回收能量最高的 baseline："
            f"{best.get('scenario_id')} / {best.get('baseline_label')} → "
            f"{float(best.get('captured_energy_kWh', 0.0)):.4f} kWh"
        )
        print()

    if outdir is not None:
        json_path, csv_path = _write_summary(outdir, all_rows, paths, bundle, config)
        readme = _write_readme(outdir, profiles, all_rows)
        print("已写出：")
        for path in (json_path, csv_path, readme):
            print(f"  - {path}")

    print()
    print(RESULT_DISCLAIMER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
