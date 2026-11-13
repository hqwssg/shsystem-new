"""验证重空协同主流程（run_project.py heavy-empty-plan）产出五类业务输出。

本用例走的是**主运行入口**（而不是直接调用优化器模块），确保五类派生输出
真正接入工作区级产物，并校验其 schema、类型、值域、OD 一致性与上下界关系。
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heavy_empty_network_optimizer import DISPATCH_SCHEME_OUTPUT_FILES, load_he_input_template
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("heavy_empty_plan_outputs")

HEADER_EXPECTATIONS = {
    "periodic_headway_recommendations.csv": {
        "candidate_id", "period_start_s", "period_end_s", "train_type", "departure_count",
        "recommended_headway_s", "observed_min_headway_s", "observed_avg_headway_s",
        "observed_max_headway_s", "basis",
    },
    "od_large_small_train_ratio.csv": {
        "candidate_id", "origin_station", "destination_station", "large_train_count",
        "small_train_count", "total_train_count", "large_train_ratio", "small_train_ratio",
        "ratio_text", "basis",
    },
    "combination_station_connection_rhythm.csv": {
        "candidate_id", "station_name", "station_role", "operation_count", "connection_count",
        "recommended_formation_rhythm_s", "minimum_operation_time_s", "capacity_per_slot",
        "connection_model_status", "basis",
    },
    "station_wait_bounds.csv": {
        "candidate_id", "station_name", "wait_lower_bound_s", "wait_upper_bound_s",
        "observed_wait_count", "data_status", "basis",
    },
    "section_station_capacity_utilization.csv": {
        "candidate_id", "resource_type", "resource_id", "period_start_s", "period_end_s",
        "used_train_count", "capacity_per_slot", "utilization_ratio", "over_capacity", "basis",
    },
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_main_entry(scenario_ids: list[str]) -> None:
    command = [
        sys.executable,
        "run_project.py",
        "heavy-empty-plan",
        "--template",
        str(TEMPLATE),
        "--output-dir",
        str(OUTPUT_ROOT),
        "--population-size",
        "6",
        "--generations",
        "2",
    ]
    for scenario_id in scenario_ids:
        command.extend(["--scenario-id", scenario_id])
    completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    bundle = load_he_input_template(TEMPLATE)
    scenario_ids = sorted(bundle.scenarios)
    od_pairs = {
        (demand.origin_station, demand.destination_station) for demand in bundle.demands
    }
    _run_main_entry(scenario_ids)

    manifest_path = OUTPUT_ROOT / "heavy_empty_plan_manifest.json"
    if not manifest_path.is_file():
        raise AssertionError("主入口必须写出 heavy_empty_plan_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if list(manifest["scheme_output_files"]) != list(DISPATCH_SCHEME_OUTPUT_FILES):
        raise AssertionError("manifest 记录的五类输出文件名与规范常量不一致")

    for scenario_id in scenario_ids:
        scenario_dir = OUTPUT_ROOT / scenario_id
        recorded = manifest["scenarios"][scenario_id]["scheme_outputs"]

        # 1) 五类输出必须存在、非空、表头完整。
        for filename in DISPATCH_SCHEME_OUTPUT_FILES:
            path = scenario_dir / filename
            if not path.is_file():
                raise AssertionError(f"缺少五类输出之一：{path}")
            if recorded[filename] != str(path):
                raise AssertionError(f"manifest 记录的路径与产物不一致：{filename}")
            rows = _read_csv(path)
            if not rows:
                raise AssertionError(f"五类输出不得为空：{path}")
            missing_columns = HEADER_EXPECTATIONS[filename] - set(rows[0])
            if missing_columns:
                raise AssertionError(f"{filename} 缺少字段：{sorted(missing_columns)}")

        # 2) 时段化发车间隔建议：发车数为正、建议间隔为正、观测间隔非负且有序。
        headway_rows = _read_csv(scenario_dir / "periodic_headway_recommendations.csv")
        for row in headway_rows:
            if int(row["departure_count"]) < 1:
                raise AssertionError(f"时段发车数必须为正：{row}")
            if float(row["recommended_headway_s"]) <= 0.0:
                raise AssertionError(f"建议发车间隔必须为正：{row}")
            if int(row["period_start_s"]) >= int(row["period_end_s"]):
                raise AssertionError(f"时段上下界必须递增：{row}")
            if row["observed_min_headway_s"]:
                observed = [
                    float(row["observed_min_headway_s"]),
                    float(row["observed_avg_headway_s"]),
                    float(row["observed_max_headway_s"]),
                ]
                if observed != sorted(observed) or observed[0] < 0.0:
                    raise AssertionError(f"观测间隔必须非负且 min<=avg<=max：{row}")

        # 3) OD 维度大/小列配比：数量守恒、比例自洽、OD 必须来自模板需求。
        od_rows = _read_csv(scenario_dir / "od_large_small_train_ratio.csv")
        for row in od_rows:
            large = int(row["large_train_count"])
            small = int(row["small_train_count"])
            total = int(row["total_train_count"])
            if large < 0 or small < 0:
                raise AssertionError(f"OD 配比计数不得为负：{row}")
            if large + small != total or total < 1:
                raise AssertionError(f"OD 大/小列数量必须守恒：{row}")
            if abs(float(row["large_train_ratio"]) + float(row["small_train_ratio"]) - 1.0) > 1e-6:
                raise AssertionError(f"OD 大/小列比例之和必须为 1：{row}")
            if row["ratio_text"] != f"{large}:{small}":
                raise AssertionError(f"OD 比例文本与计数不一致：{row}")
            if (row["origin_station"], row["destination_station"]) not in od_pairs:
                raise AssertionError(f"OD 输出出现模板需求之外的起讫站：{row}")

        # 4) 组合站接续与编组节拍：作业量非负、编组节拍为正、站场能力为正。
        rhythm_rows = _read_csv(scenario_dir / "combination_station_connection_rhythm.csv")
        for row in rhythm_rows:
            operations = int(row["operation_count"])
            connections = int(row["connection_count"])
            if operations < 0 or connections < 0 or connections > operations:
                raise AssertionError(f"接续计数异常：{row}")
            if float(row["recommended_formation_rhythm_s"]) <= 0.0:
                raise AssertionError(f"编组节拍必须为正：{row}")
            if int(row["capacity_per_slot"]) < 1:
                raise AssertionError(f"站场每时段能力必须为正：{row}")
            if row["connection_model_status"] not in {
                "explicit_combination_arcs", "no_explicit_combination_arc_in_current_model"
            }:
                raise AssertionError(f"接续建模状态取值非法：{row}")

        # 5) 在站等待上下界：下界不得大于上界。
        wait_rows = _read_csv(scenario_dir / "station_wait_bounds.csv")
        for row in wait_rows:
            lower = int(row["wait_lower_bound_s"])
            upper = int(row["wait_upper_bound_s"])
            if lower < 0 or lower > upper:
                raise AssertionError(f"在站等待上下界关系错误：{row}")
            if int(row["observed_wait_count"]) < 0:
                raise AssertionError(f"等待次数不得为负：{row}")

        # 6) 区段与站作业容量利用图谱：利用率定义自洽、超容量标记与计数一致。
        capacity_rows = _read_csv(scenario_dir / "section_station_capacity_utilization.csv")
        if not capacity_rows:
            raise AssertionError("容量利用图谱不得为空")
        for row in capacity_rows:
            used = int(row["used_train_count"])
            capacity = int(row["capacity_per_slot"])
            ratio = float(row["utilization_ratio"])
            over = row["over_capacity"].strip().lower() == "true"
            if used < 0 or capacity < 1:
                raise AssertionError(f"容量利用计数异常：{row}")
            if abs(ratio - used / capacity) > 1e-6:
                raise AssertionError(f"利用率必须等于 used/capacity：{row}")
            if over != (used > capacity):
                raise AssertionError(f"超容量标记与计数不一致：{row}")
            if row["resource_type"] not in {"section", "station"}:
                raise AssertionError(f"资源类型非法：{row}")
            if int(row["period_start_s"]) >= int(row["period_end_s"]):
                raise AssertionError(f"时段上下界必须递增：{row}")

        # 7) summary.json 必须登记五类输出，供平台/报告引用。
        summary = json.loads((scenario_dir / "summary.json").read_text(encoding="utf-8"))
        if not summary.get("dispatch_scheme_outputs"):
            raise AssertionError("summary.json 必须登记 dispatch_scheme_outputs")

    print("heavy-empty plan outputs verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
