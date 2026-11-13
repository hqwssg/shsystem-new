"""验证长测性能门禁的配置校验、聚合统计和失败判定。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.run_long_dispatch_tests import DEFAULT_GATE_CONFIG, _evaluate_test, _load_gate_config


def main() -> None:
    """覆盖正常、功能失败、耗时回归和内存回归四类结论。"""
    config = _load_gate_config(DEFAULT_GATE_CONFIG)
    expected = {
        "heavy_empty_network", "rolling_optimizer", "timetable_optimizer", "timetable_resources",
        "dispatch_output_path", "historical_disturbance_replay", "joint_parameter_robustness",
    }
    if set(config["tests"]) != expected:
        raise AssertionError("冻结门禁必须完整覆盖七项长测。")
    rule = {
        "script": "tests/smoke/verify_dispatch_output_path.py", "timeout_s": 10, "repeat_count": 2,
        "baseline_median_elapsed_s": 1.0, "max_median_elapsed_s": 2.0, "max_peak_rss_mb": 100.0,
    }
    passing = _evaluate_test("probe", rule, [
        {"passed": True, "elapsed_s": 1.0, "peak_rss_mb": 80.0, "memory_sample_count": 2},
        {"passed": True, "elapsed_s": 1.4, "peak_rss_mb": 90.0, "memory_sample_count": 2},
    ])
    if not passing["passed"] or passing["median_elapsed_s"] != 1.2 or passing["peak_rss_mb"] != 90.0:
        raise AssertionError(f"正常聚合结果错误：{passing}")
    functional = _evaluate_test("probe", rule, [
        {"passed": True, "elapsed_s": 1.0, "peak_rss_mb": 80.0, "memory_sample_count": 2},
        {"passed": False, "elapsed_s": 10.1, "peak_rss_mb": 90.0},
    ])
    if functional["passed"] or functional["violations"][0]["metric"] != "successful_repeat_count":
        raise AssertionError("功能失败或测量不完整必须阻断门禁。")
    elapsed = _evaluate_test("probe", rule, [
        {"passed": True, "elapsed_s": 2.1, "peak_rss_mb": 80.0, "memory_sample_count": 2},
        {"passed": True, "elapsed_s": 2.3, "peak_rss_mb": 90.0, "memory_sample_count": 2},
    ])
    if elapsed["passed"] or {item["metric"] for item in elapsed["violations"]} != {"median_elapsed_s"}:
        raise AssertionError("中位耗时超线必须阻断门禁。")
    memory = _evaluate_test("probe", rule, [
        {"passed": True, "elapsed_s": 1.0, "peak_rss_mb": 80.0, "memory_sample_count": 2},
        {"passed": True, "elapsed_s": 1.1, "peak_rss_mb": 100.1, "memory_sample_count": 2},
    ])
    if memory["passed"] or {item["metric"] for item in memory["violations"]} != {"peak_rss_mb"}:
        raise AssertionError("任一轮峰值内存超线必须阻断门禁。")
    missing_sample = _evaluate_test("probe", rule, [
        {"passed": True, "elapsed_s": 1.0, "peak_rss_mb": 0.0, "memory_sample_count": 0},
        {"passed": True, "elapsed_s": 1.1, "peak_rss_mb": 80.0, "memory_sample_count": 2},
    ])
    if missing_sample["passed"] or "memory_sample_count" not in {
        item["metric"] for item in missing_sample["violations"]
    }:
        raise AssertionError("缺失进程树内存样本时门禁必须失败。")
    print("long test performance gate smoke: PASS")


if __name__ == "__main__":
    main()
