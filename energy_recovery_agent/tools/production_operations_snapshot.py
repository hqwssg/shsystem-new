"""采集生产任务队列、数据库容量和主机磁盘指标，并按冻结策略生成告警。"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import psycopg


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "operations" / "production_assurance_policy.json"
SEVERITY_ORDER = {"ok": 0, "warning": 1, "critical": 2}


def load_policy(path: Path) -> dict[str, Any]:
    """读取运维策略并校验监控阈值的结构和方向。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("生产保障策略schema_version必须为1.0。")
    thresholds = payload.get("monitoring", {}).get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("生产保障策略缺少监控阈值。")
    for metric, rule in thresholds.items():
        if not isinstance(rule, dict) or rule.get("direction") not in {"min", "max"}:
            raise ValueError(f"指标{metric}的阈值规则无效。")
        for field in ("warning", "critical"):
            value = rule.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"指标{metric}的{field}必须为有限数值。")
        warning, critical = float(rule["warning"]), float(rule["critical"])
        if (rule["direction"] == "max" and warning > critical) or (
            rule["direction"] == "min" and warning < critical
        ):
            raise ValueError(f"指标{metric}的warning与critical顺序错误。")
    return payload


def evaluate_metric(metric: str, value: float, rule: Mapping[str, Any]) -> dict[str, Any]:
    """根据单个阈值规则返回稳定的告警等级和解释。"""
    warning = float(rule["warning"])
    critical = float(rule["critical"])
    direction = str(rule["direction"])
    if direction == "max":
        severity = "critical" if value >= critical else "warning" if value >= warning else "ok"
    else:
        severity = "critical" if value <= critical else "warning" if value <= warning else "ok"
    return {
        "metric": metric,
        "value": value,
        "severity": severity,
        "direction": direction,
        "warning_threshold": warning,
        "critical_threshold": critical,
    }


def collect_database_metrics(database_url: str, *, recent_window_hours: int) -> dict[str, Any]:
    """使用只读SQL采集任务、租约、失败率、数据库与工件容量。"""
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, now()")
            database_name, current_user, database_time = cursor.fetchone()
            cursor.execute(
                "SELECT status, count(*) FROM energy_recovery.simulation_run GROUP BY status"
            )
            status_counts = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT COALESCE(EXTRACT(EPOCH FROM (now() - min(queued_at))), 0)
                FROM energy_recovery.simulation_run WHERE status = 'pending'
                """
            )
            oldest_pending_age_s = float(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COALESCE(max(EXTRACT(EPOCH FROM (
                    now() - COALESCE(heartbeat_at, started_at, queued_at)
                ))), 0)
                FROM energy_recovery.simulation_run
                WHERE status IN ('validating', 'running')
                """
            )
            stale_heartbeat_age_s = float(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT count(*) FROM energy_recovery.simulation_run
                WHERE status IN ('validating', 'running') AND lease_expires_at < now()
                """
            )
            expired_active_lease_count = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT count(*) FILTER (WHERE status = 'failed'), count(*)
                FROM energy_recovery.simulation_run
                WHERE finished_at >= now() - (%s * interval '1 hour')
                  AND status IN ('succeeded', 'failed')
                """,
                (recent_window_hours,),
            )
            failed_count, terminal_count = (int(value) for value in cursor.fetchone())
            cursor.execute("SELECT pg_database_size(current_database())")
            database_size_bytes = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*), COALESCE(sum(content_size_bytes), 0) "
                "FROM energy_recovery.simulation_result_artifact"
            )
            artifact_count, artifact_size_bytes = (int(value) for value in cursor.fetchone())
    return {
        "database": str(database_name),
        "current_user": str(current_user),
        "database_time": database_time.isoformat(),
        "status_counts": status_counts,
        "pending_count": status_counts.get("pending", 0),
        "oldest_pending_age_s": round(oldest_pending_age_s, 3),
        "stale_heartbeat_age_s": round(stale_heartbeat_age_s, 3),
        "expired_active_lease_count": expired_active_lease_count,
        "recent_failed_count": failed_count,
        "recent_terminal_count": terminal_count,
        "recent_failure_rate": round(failed_count / terminal_count, 6) if terminal_count else 0.0,
        "database_size_bytes": database_size_bytes,
        "artifact_count": artifact_count,
        "artifact_size_bytes": artifact_size_bytes,
    }


def build_snapshot(database_url: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    """组合数据库和主机指标，并应用失败率最小样本量规则。"""
    monitoring = policy["monitoring"]
    metrics = collect_database_metrics(
        database_url, recent_window_hours=int(monitoring["recent_window_hours"])
    )
    disk = shutil.disk_usage(ROOT)
    metrics["host_disk_free_percent"] = round(disk.free / disk.total * 100, 3)
    alerts = []
    minimum_sample = int(monitoring["minimum_failure_rate_sample_count"])
    for metric, rule in monitoring["thresholds"].items():
        alert = evaluate_metric(metric, float(metrics[metric]), rule)
        if metric == "recent_failure_rate" and metrics["recent_terminal_count"] < minimum_sample:
            alert["severity"] = "ok"
            alert["suppressed"] = True
            alert["suppression_reason"] = (
                f"最近终态样本{metrics['recent_terminal_count']}小于最小样本{minimum_sample}。"
            )
        alerts.append(alert)
    highest = max((item["severity"] for item in alerts), key=SEVERITY_ORDER.get)
    return {
        "schema_version": "1.0",
        "policy_version": policy["policy_version"],
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "highest_severity": highest,
        "healthy": highest != "critical",
        "metrics": metrics,
        "alerts": alerts,
        "limitations": [
            "数据库只能观测活动任务心跳；空闲worker存活性必须由进程管理器监控。",
            "当前阈值为部署前基线，尚未由甲方按正式SLA批准。",
        ],
    }


def write_reports(output_dir: Path, snapshot: Mapping[str, Any]) -> None:
    """写出不含数据库连接串的JSON和Markdown运行快照。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "production_operations_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metrics = snapshot["metrics"]
    lines = [
        "# 生产运行状态快照", "",
        f"- 最高告警等级：`{snapshot['highest_severity']}`",
        f"- 数据库：`{metrics['database']}`",
        f"- 数据库账号：`{metrics['current_user']}`",
        f"- 策略版本：`{snapshot['policy_version']}`", "",
        "| 指标 | 当前值 | 等级 | Warning | Critical |", "| --- | ---: | --- | ---: | ---: |",
    ]
    lines.extend(
        f"| `{item['metric']}` | {item['value']} | `{item['severity']}` | "
        f"{item['warning_threshold']} | {item['critical_threshold']} |"
        for item in snapshot["alerts"]
    )
    lines.extend(["", "## 限制", ""])
    lines.extend(f"- {item}" for item in snapshot["limitations"])
    lines.extend(["", "连接串和凭据不会写入报告。当前阈值是部署前基线，不是甲方生产SLA。"])
    (output_dir / "PRODUCTION_OPERATIONS_SNAPSHOT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("SIMULATION_READONLY_DATABASE_URL"))
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "production_operations_snapshot")
    parser.add_argument("--fail-on", choices=("never", "warning", "critical"), default="critical")
    args = parser.parse_args(argv)
    if not args.database_url:
        raise RuntimeError("必须通过--database-url或SIMULATION_READONLY_DATABASE_URL提供只读连接串。")
    policy_path = args.policy if args.policy.is_absolute() else ROOT / args.policy
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    snapshot = build_snapshot(args.database_url, load_policy(policy_path))
    write_reports(output_dir, snapshot)
    print(json.dumps({
        "healthy": snapshot["healthy"], "highest_severity": snapshot["highest_severity"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False))
    if args.fail_on == "never":
        return 0
    return 1 if SEVERITY_ORDER[snapshot["highest_severity"]] >= SEVERITY_ORDER[args.fail_on] else 0


if __name__ == "__main__":
    raise SystemExit(main())
