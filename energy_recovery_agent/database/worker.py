"""从数据库领取平台任务、运行现有算法并持久化结果。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID
import json
import locale
import shutil
import subprocess
import sys
import tempfile
import time
import csv
import io

from .file_names import records_to_algorithm_names, to_algorithm_path
from .mysql import RunLeaseLostError, SimulationRepository
from .parameters import BOOLEAN_FLAGS, PARAMETER_FLAGS, validate_run_parameters
from .solver_budget import apply_parameter_overrides, build_solve_attempts
from .snapshots import FileRecord, materialize_file_records, record_from_bytes, snapshot_manifest


ROOT = Path(__file__).resolve().parents[1]
DATABASE_STORAGE_PARAMETERS_FILE = "storage_devices.json"


class SolveBudgetExceededError(TimeoutError):
    """算法子进程超过本次墙钟预算。"""

    def __init__(
        self, timeout_s: int, stdout: str = "", stderr: str = "", detail: str = ""
    ) -> None:
        message = f"算法在{timeout_s}秒墙钟预算内未完成。"
        if detail:
            message = f"{message} {detail}"
        super().__init__(message)
        self.timeout_s = timeout_s
        self.stdout = stdout
        self.stderr = stderr


def _decode_subprocess_output(value: bytes | str | None) -> str:
    """稳健解码Windows算法子进程输出，避免管道读取线程因编码失败退出。"""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    encodings = ("utf-8", locale.getpreferredencoding(False), "gb18030")
    for encoding in dict.fromkeys(encodings):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def bind_database_storage_parameters(
    records: Sequence[FileRecord],
    storage_devices: Sequence[Mapping[str, Any]],
) -> tuple[FileRecord, ...]:
    """数据库额定参数优先；版本文件仅补充尚无数据库列的自放电率。"""

    if not storage_devices:
        by_path = {record.relative_path: record for record in records}
        def csv_rows(name):
            record = by_path.get(name)
            return list(csv.DictReader(io.StringIO(record.content.decode('utf-8-sig')))) if record else []
        arms = csv_rows('power_arm_intervals.csv')
        zones = csv_rows('energy_transfer_zones.csv')
        physical_reference = any(row.get('storage_section_id') or row.get('storage_code') for row in zones)
        physical_reference = physical_reference or any(
            (row.get('storage_section_id') or row.get('storage_code')) and not str(row.get('storage_status','')).startswith('planning_')
            for row in arms)
        flexible_only = bool(zones) and all(row.get('implementation_status') or row.get('active_in_operational_baseline') for row in zones)
        old_devices = by_path.get(DATABASE_STORAGE_PARAMETERS_FILE)
        if old_devices and json.loads(old_devices.content.decode('utf-8-sig')):
            physical_reference = True
        if not physical_reference and flexible_only and 'battery.json' in by_path:
            # The frozen aggregate battery remains an explicit simulation assumption, not a device inventory.
            return tuple(record for record in records if record.relative_path != DATABASE_STORAGE_PARAMETERS_FILE)
        raise ValueError("数据库版本没有可供算法使用的储能设备参数。")
    by_path = {record.relative_path: record for record in records}
    metadata_by_id = {}
    source = by_path.get(DATABASE_STORAGE_PARAMETERS_FILE)
    if source is not None:
        rows = json.loads(source.content.decode("utf-8-sig"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("版本中的storage_devices.json必须是JSON对象数组。")
        for row in rows:
            code = str(row.get("storage_section_id") or row.get("storage_code") or "").strip()
            if not code or code in metadata_by_id:
                raise ValueError("版本中的储能设备编号不能为空或重复。")
            metadata_by_id[code] = row
    devices = []
    for source_device in storage_devices:
        device = dict(source_device)
        code = str(device.get("storage_section_id") or device.get("storage_code") or "").strip()
        metadata = metadata_by_id.get(code, {})
        device.setdefault("self_discharge_rate_per_hour", metadata.get("self_discharge_rate_per_hour", 0.0))
        rate = device["self_discharge_rate_per_hour"]
        if isinstance(rate, bool):
            raise ValueError("储能自放电率必须是0到1之间的有限数值。")
        try:
            rate = float(rate)
        except (ValueError, TypeError) as exc:
            raise ValueError("储能自放电率必须是0到1之间的有限数值。") from exc
        if not 0.0 <= rate <= 1.0:
            raise ValueError("储能自放电率必须是0到1之间的有限数值。")
        device["self_discharge_rate_per_hour"] = rate
        devices.append(device)
    payload = json.dumps(devices, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    generated = record_from_bytes(DATABASE_STORAGE_PARAMETERS_FILE, payload)
    by_path[generated.relative_path] = generated
    return tuple(by_path[path] for path in sorted(by_path))


def _logical_file(root: Path, value: Any, default: str) -> Path:
    """将平台提交的逻辑路径限制在冻结快照目录内。"""

    relative = to_algorithm_path(str(value or default).replace("\\", "/"))
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"任务文件路径越界：{relative}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"任务引用的快照文件不存在：{relative}")
    return candidate


def build_algorithm_command(
    run_type: str,
    parameters: Mapping[str, Any],
    *,
    data_dir: Path,
    output_dir: Path,
    python_executable: str = sys.executable,
) -> list[str]:
    """从字段白名单构造命令，数据库内容不能注入任意命令行选项。"""

    if run_type not in PARAMETER_FLAGS:
        raise ValueError(f"不支持的数据库任务类型：{run_type}")
    validate_run_parameters(run_type, parameters)
    command = [python_executable, str(ROOT / "run_project.py")]
    if run_type == "dispatch":
        command.extend(["dispatch-case", "--data-dir", str(data_dir), "--output-dir", str(output_dir)])
        command.extend(["--optimization-mode", "dispatch_only"])
    elif run_type == "timetable_audit":
        timetable = _logical_file(data_dir, parameters.get("timetable_relative_path"), "platform/timetable.csv")
        command.extend([
            "audit-timetable", "--data-dir", str(data_dir), "--timetable", str(timetable),
            "--output-dir", str(output_dir),
        ])
    elif run_type == "timetable_optimization":
        timetable = _logical_file(data_dir, parameters.get("timetable_relative_path"), "platform/timetable.csv")
        command.extend([
            "optimize-timetable", "--data-dir", str(data_dir), "--timetable", str(timetable),
            "--output-dir", str(output_dir),
        ])
    elif run_type == "rolling_rescheduling":
        command.extend([
            "benchmark-rolling-rescheduling",
            "--data-dir", str(data_dir),
            "--output-dir", str(output_dir),
        ])
        replay_relative_path = parameters.get("disturbance_history_relative_path")
        if replay_relative_path is not None:
            replay_path = _logical_file(data_dir, replay_relative_path, "")
            command.extend([
                "--disturbance-history", str(replay_path),
                "--disturbance-history-label", str(replay_relative_path).replace("\\", "/"),
            ])
    elif run_type == "storage_planning":
        command.extend(["plan-storage", "--input-dir", str(data_dir), "--data-dir", str(data_dir),
                        "--output-dir", str(output_dir), "--power-arm-path", str(data_dir / "power_arm_intervals.csv")])
    else:
        ranges_path = _logical_file(
            data_dir, parameters.get("parameter_ranges_relative_path"), ""
        )
        command.extend([
            "benchmark-joint-parameter-robustness",
            "--data-dir", str(data_dir),
            "--parameter-ranges", str(ranges_path),
            "--output-dir", str(output_dir),
        ])
    allowed = PARAMETER_FLAGS[run_type]
    boolean_flags = BOOLEAN_FLAGS[run_type]
    for name, flag in allowed.items():
        value = parameters.get(name)
        if value is None:
            continue
        command.extend([flag, str(value)])
    if run_type == "rolling_rescheduling" and "storage_devices" in parameters:
        command.extend([
            "--storage-devices-json",
            json.dumps(
                parameters["storage_devices"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ])
    for name, flag in boolean_flags.items():
        if bool(parameters.get(name, False)):
            command.append(flag)
    return command


def _subprocess_runner(
    command: Sequence[str],
    cwd: Path,
    *,
    heartbeat: Callable[[], Any] | None = None,
    heartbeat_interval_s: int = 60,
    timeout_s: int | None = None,
) -> subprocess.CompletedProcess:
    """运行算法子进程，持续续租并强制执行总墙钟预算。"""

    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s必须大于0。")
    budget_s = int(timeout_s) if timeout_s is not None else None

    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    started = time.monotonic()
    try:
        while True:
            elapsed = time.monotonic() - started
            remaining = None if budget_s is None else budget_s - elapsed
            if remaining is not None and remaining <= 0:
                assert budget_s is not None
                raise SolveBudgetExceededError(budget_s)
            try:
                wait_s = heartbeat_interval_s if remaining is None else min(heartbeat_interval_s, remaining)
                stdout, stderr = process.communicate(timeout=wait_s)
                return subprocess.CompletedProcess(
                    list(command),
                    process.returncode,
                    _decode_subprocess_output(stdout),
                    _decode_subprocess_output(stderr),
                )
            except subprocess.TimeoutExpired:
                if budget_s is not None and time.monotonic() - started >= budget_s:
                    raise SolveBudgetExceededError(budget_s)
                if heartbeat is not None:
                    heartbeat()
    except BaseException as exc:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        if isinstance(exc, SolveBudgetExceededError):
            exc.stdout = _decode_subprocess_output(stdout)
            exc.stderr = _decode_subprocess_output(stderr)
        raise


def execute_claimed_run(
    repository: SimulationRepository,
    job: Mapping[str, Any],
    *,
    runner: Callable[[Sequence[str], Path], Any] = _subprocess_runner,
    lease_seconds: int = 300,
    heartbeat_interval_s: int = 60,
    resource_profile: str = "standard",
) -> dict:
    """执行一个已领取任务；任何异常都会写回failed状态。"""

    run_id = UUID(str(job["run_id"]))
    version_id = UUID(str(job["version_id"]))
    worker_id = str(job.get("worker_id") or "").strip()
    if not worker_id:
        raise ValueError("已领取任务缺少worker_id。")
    try:
        lease_token = UUID(str(job["lease_token"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("已领取任务缺少有效lease_token。") from exc
    if heartbeat_interval_s <= 0 or heartbeat_interval_s >= lease_seconds:
        raise ValueError("heartbeat_interval_s必须大于0且小于lease_seconds。")
    parameters = dict(job["parameters"])
    try:
        records = repository.load_version_files(version_id)
        records = records_to_algorithm_names(records)
        if job["run_type"] == "storage_planning":
            from .planning import validate_planning_records, normalized_planning_records
            records = normalized_planning_records(records)
            validate_run_parameters("storage_planning", parameters)
            validate_planning_records(records, parameters)
        else:
            storage_devices = repository.load_storage_device_parameters(version_id)
            records = bind_database_storage_parameters(records, storage_devices)
        manifest = snapshot_manifest(records)
        repository.freeze_run_snapshot(
            run_id,
            version_id,
            manifest,
            worker_id=worker_id,
            lease_token=lease_token,
        )
        with tempfile.TemporaryDirectory(prefix=f"simulation_run_{run_id}_") as temp_name:
            work_dir = Path(temp_name)
            data_dir = work_dir / "input"
            materialize_file_records(records, data_dir)
            run_type = str(job["run_type"])
            attempts = build_solve_attempts(run_type, parameters, resource_profile)
            heartbeat = lambda: repository.heartbeat_run(
                run_id,
                worker_id,
                lease_token,
                lease_seconds=lease_seconds,
            )
            heartbeat()
            attempt_records: list[dict[str, Any]] = []
            completed = None
            selected_command: list[str] | None = None
            selected_output_dir: Path | None = None
            for attempt_index, attempt in enumerate(attempts, start=1):
                attempt_output_dir = work_dir / "attempts" / f"{attempt_index:02d}_{attempt.name}"
                effective_parameters = apply_parameter_overrides(
                    parameters, attempt.parameter_overrides
                )
                command = build_algorithm_command(
                    run_type,
                    effective_parameters,
                    data_dir=data_dir,
                    output_dir=attempt_output_dir,
                )
                attempt_started = time.monotonic()
                try:
                    if runner is _subprocess_runner:
                        current = _subprocess_runner(
                            command,
                            ROOT,
                            heartbeat=heartbeat,
                            heartbeat_interval_s=heartbeat_interval_s,
                            timeout_s=attempt.wall_time_s,
                        )
                    else:
                        current = runner(command, ROOT)
                        heartbeat()
                except SolveBudgetExceededError as exc:
                    attempt_records.append({
                        "attempt": attempt_index,
                        "name": attempt.name,
                        "status": "timeout",
                        "degraded": attempt.degraded,
                        "wall_time_limit_s": attempt.wall_time_s,
                        "wall_time_s": round(time.monotonic() - attempt_started, 6),
                        "parameter_overrides": dict(attempt.parameter_overrides),
                        "stderr_tail": exc.stderr[-2000:],
                    })
                    continue
                return_code = int(getattr(current, "returncode", 1))
                attempt_records.append({
                    "attempt": attempt_index,
                    "name": attempt.name,
                    "status": "succeeded" if return_code == 0 else "failed",
                    "degraded": attempt.degraded,
                    "wall_time_limit_s": attempt.wall_time_s,
                    "wall_time_s": round(time.monotonic() - attempt_started, 6),
                    "parameter_overrides": dict(attempt.parameter_overrides),
                    "return_code": return_code,
                })
                if return_code != 0:
                    stderr_tail = _decode_subprocess_output(
                        getattr(current, "stderr", "")
                    )[-2000:].strip()
                    stdout_tail = _decode_subprocess_output(
                        getattr(current, "stdout", "")
                    )[-1000:].strip()
                    diagnostic = stderr_tail or stdout_tail or "子进程没有输出诊断信息"
                    raise RuntimeError(
                        f"算法进程返回非零状态：{return_code}；输出尾部：{diagnostic}"
                    )
                completed = current
                selected_command = command
                selected_output_dir = attempt_output_dir
                break
            if completed is None or selected_command is None or selected_output_dir is None:
                attempt_summary = ", ".join(
                    f"{item['name']}={item['status']}" for item in attempt_records
                )
                raise SolveBudgetExceededError(
                    sum(item.wall_time_s for item in attempts),
                    detail=f"全部有界尝试均已耗尽：{attempt_summary}",
                )
            output_dir = work_dir / "output"
            shutil.copytree(selected_output_dir, output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "database_worker_stdout.txt").write_text(
                str(getattr(completed, "stdout", "")), encoding="utf-8"
            )
            (output_dir / "database_worker_stderr.txt").write_text(
                str(getattr(completed, "stderr", "")), encoding="utf-8"
            )
            (output_dir / "database_worker_command.json").write_text(
                json.dumps(selected_command, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            selected_attempt = attempt_records[-1]
            (output_dir / "solver_resource_report.json").write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "run_type": run_type,
                    "resource_profile": resource_profile,
                    "final_status": "succeeded_degraded" if selected_attempt["degraded"] else "succeeded",
                    "degradation_applied": bool(selected_attempt["degraded"]),
                    "timeout_is_infeasibility": False,
                    "selected_attempt": selected_attempt["name"],
                    "effective_parameters": apply_parameter_overrides(
                        parameters, attempts[len(attempt_records) - 1].parameter_overrides
                    ),
                    "attempts": attempt_records,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            handoff = ROOT / 'FRONTEND_HANDOFF_MANIFEST.json'
            context = json.loads(handoff.read_text(encoding='utf-8')) if handoff.is_file() else {}
            execution_context = {
                'source_release_version': context.get('source_release_version', 'local'),
                'phase': context.get('phase', 'simulation'),
                'ready_for_conclusions': context.get('ready_for_conclusions', False),
                'version_id': str(version_id),
            }
            for name in ('summary.json','audit_summary.json','optimizer_summary.json','benchmark_summary.json','joint_robustness_summary.json','storage_planning_summary.json'):
                path = output_dir / name
                if path.is_file():
                    summary = json.loads(path.read_text(encoding='utf-8'))
                    summary['algorithm_context'] = execution_context
                    path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
            heartbeat()
            result = repository.persist_result(
                run_id,
                output_dir,
                worker_id=worker_id,
                lease_token=lease_token,
                settlement_step_s=int(parameters.get("settlement_step_s", 10)),
            )
            return {"run_id": str(run_id), "status": "succeeded", **result}
    except BaseException as exc:
        try:
            repository.mark_failed(
                run_id,
                f"{type(exc).__name__}: {exc}",
                worker_id=worker_id,
                lease_token=lease_token,
            )
        except RunLeaseLostError:
            # 租约失效后任务可能已被回收或取消，旧工作进程不得覆盖新状态。
            pass
        raise


def run_one_pending(
    repository: SimulationRepository,
    worker_id: str,
    *,
    lease_seconds: int = 300,
    heartbeat_interval_s: int = 60,
    resource_profile: str = "standard",
) -> dict | None:
    """领取并执行一个任务；没有待执行任务时返回None。"""

    job = repository.claim_next_run(worker_id, lease_seconds=lease_seconds)
    if job is None:
        return None
    return execute_claimed_run(
        repository,
        job,
        lease_seconds=lease_seconds,
        heartbeat_interval_s=heartbeat_interval_s,
        resource_profile=resource_profile,
    )


def run_pending_run(
    repository: SimulationRepository,
    worker_id: str,
    run_id: UUID,
    *,
    lease_seconds: int = 300,
    heartbeat_interval_s: int = 60,
    resource_profile: str = "standard",
) -> dict | None:
    """领取并执行指定任务；任务不存在或已被领取时返回None。"""

    job = repository.claim_run(run_id, worker_id, lease_seconds=lease_seconds)
    if job is None:
        return None
    return execute_claimed_run(
        repository,
        job,
        lease_seconds=lease_seconds,
        heartbeat_interval_s=heartbeat_interval_s,
        resource_profile=resource_profile,
    )
