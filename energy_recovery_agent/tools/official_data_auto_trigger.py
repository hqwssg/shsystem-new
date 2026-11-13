# 模块功能说明：检测完整的正式数据交付包，冻结输入快照，并自动启动正式实验总控。

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.formal_experiment_controller import run_formal_experiment_suite
from tools.official_data_readiness_pipeline import run_pipeline as run_readiness_pipeline


MARKER_NAME = "OFFICIAL_DATA_READY.json"
STATE_NAME = "trigger_state.json"
LATEST_SUMMARY_NAME = "latest_trigger_summary.json"
SCHEMA_VERSION = "1.0"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_EXPERIMENT_KEYS = {
    "seeds",
    "settlement_steps_s",
    "max_shift_min",
    "step_min",
    "max_dwell_extension_min",
    "max_candidates",
    "population_size",
    "generations",
    "crossover_rate",
    "mutation_rate",
    "strict_visualizations",
    "require_calibration",
}


def _utc_now() -> str:
    """返回便于审计和排序的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """先写临时文件再替换，避免进程中断留下半份状态文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _load_json(path: Path) -> Dict[str, Any]:
    """读取 JSON 对象并将格式错误转换成明确的到件错误。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"无法读取到件标记 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("到件标记必须是 JSON 对象。")
    return payload


def _safe_relative_path(root: Path, value: Any, field: str) -> Path:
    """解析包内相对路径，并拒绝绝对路径和目录穿越。"""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise ValueError(f"到件标记缺少 {field}。")
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} 必须是交付包内的安全相对路径：{text}")
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{field} 越出交付包目录：{text}") from exc
    return relative


def _sha256(path: Path) -> str:
    """分块计算文件摘要，避免大文件一次性载入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_files(package_dir: Path, marker_name: str = MARKER_NAME) -> list[Path]:
    """列出交付包载荷；到件标记自身不参与载荷摘要。"""
    return sorted(
        path for path in package_dir.rglob("*")
        if path.is_file() and path.relative_to(package_dir).as_posix() != marker_name
    )


def create_delivery_marker(
    package_dir: Path,
    *,
    delivery_id: str,
    data_dir: str,
    source_dir: str,
    timetable: str,
    window_id: str,
    calibration_summary: Optional[str] = None,
    experiment: Optional[Dict[str, Any]] = None,
    marker_name: str = MARKER_NAME,
) -> Dict[str, Any]:
    """为已复制完成的交付包生成最终标记和逐文件哈希清单。"""
    package_dir = Path(package_dir)
    if not package_dir.is_dir():
        raise ValueError(f"交付包目录不存在：{package_dir}")
    if not _SAFE_ID.fullmatch(str(delivery_id)):
        raise ValueError("delivery_id 只能包含字母、数字、点、下划线和连字符，最长80字符。")
    if not str(window_id).strip():
        raise ValueError("window_id 不能为空。")
    references = {
        "data_dir": _safe_relative_path(package_dir, data_dir, "data_dir").as_posix(),
        "source_dir": _safe_relative_path(package_dir, source_dir, "source_dir").as_posix(),
        "timetable": _safe_relative_path(package_dir, timetable, "timetable").as_posix(),
    }
    if calibration_summary:
        references["calibration_summary"] = _safe_relative_path(
            package_dir, calibration_summary, "calibration_summary"
        ).as_posix()
    for field in ("data_dir", "source_dir"):
        if not (package_dir / references[field]).is_dir():
            raise ValueError(f"{field} 指向的目录不存在：{references[field]}")
    for field in ("timetable", "calibration_summary"):
        if field in references and not (package_dir / references[field]).is_file():
            raise ValueError(f"{field} 指向的文件不存在：{references[field]}")
    files = [
        {
            "path": path.relative_to(package_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in _payload_files(package_dir, marker_name)
    ]
    if not files:
        raise ValueError("交付包没有可处理的载荷文件。")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "delivery_id": delivery_id,
        "delivered_at_utc": _utc_now(),
        "window_id": str(window_id).strip(),
        **references,
        "experiment": experiment or {},
        "files": files,
    }
    _write_json_atomic(package_dir / marker_name, payload)
    return payload


def validate_delivery(package_dir: Path, marker_name: str = MARKER_NAME) -> Dict[str, Any]:
    """验证标记、引用路径、精确文件集合、大小和 SHA-256。"""
    package_dir = Path(package_dir)
    marker_path = package_dir / marker_name
    if not marker_path.is_file():
        raise FileNotFoundError(f"尚未发现最终到件标记：{marker_path}")
    marker = _load_json(marker_path)
    if marker.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"不支持的到件标记版本：{marker.get('schema_version')}")
    delivery_id = str(marker.get("delivery_id") or "")
    if not _SAFE_ID.fullmatch(delivery_id):
        raise ValueError("delivery_id 不符合安全命名规则。")
    if not str(marker.get("window_id") or "").strip():
        raise ValueError("window_id 不能为空。")

    references = {}
    for field in ("data_dir", "source_dir", "timetable"):
        references[field] = _safe_relative_path(package_dir, marker.get(field), field)
    if marker.get("calibration_summary"):
        references["calibration_summary"] = _safe_relative_path(
            package_dir, marker["calibration_summary"], "calibration_summary"
        )
    for field in ("data_dir", "source_dir"):
        if not (package_dir / references[field]).is_dir():
            raise ValueError(f"{field} 指向的目录不存在。")
    for field in ("timetable", "calibration_summary"):
        if field in references and not (package_dir / references[field]).is_file():
            raise ValueError(f"{field} 指向的文件不存在。")

    declared_rows = marker.get("files")
    if not isinstance(declared_rows, list) or not declared_rows:
        raise ValueError("files 必须是非空的文件清单。")
    declared: Dict[str, Dict[str, Any]] = {}
    for row in declared_rows:
        if not isinstance(row, dict):
            raise ValueError("files 中的每一项必须是对象。")
        relative = _safe_relative_path(package_dir, row.get("path"), "files.path")
        key = relative.as_posix()
        if key == marker_name or key in declared:
            raise ValueError(f"文件清单包含标记文件或重复路径：{key}")
        declared[key] = row
    actual = {path.relative_to(package_dir).as_posix(): path for path in _payload_files(package_dir, marker_name)}
    if set(declared) != set(actual):
        missing = sorted(set(declared) - set(actual))
        extra = sorted(set(actual) - set(declared))
        raise ValueError(f"交付包文件集合与标记不一致；缺失={missing}，未登记={extra}")
    for key, path in actual.items():
        row = declared[key]
        if int(row.get("size", -1)) != path.stat().st_size:
            raise ValueError(f"文件大小不一致：{key}")
        if str(row.get("sha256") or "").lower() != _sha256(path):
            raise ValueError(f"文件 SHA-256 不一致：{key}")

    experiment = marker.get("experiment", {})
    if not isinstance(experiment, dict):
        raise ValueError("experiment 必须是对象。")
    unknown = sorted(set(experiment) - _EXPERIMENT_KEYS)
    if unknown:
        raise ValueError(f"experiment 含不支持参数：{unknown}")
    fingerprint = hashlib.sha256(marker_path.read_bytes()).hexdigest()
    return {
        "marker": marker,
        "marker_path": marker_path,
        "fingerprint": fingerprint,
        "references": references,
        "actual_files": actual,
    }


def _pid_is_running(pid: int) -> bool:
    """保守判断锁文件记录的进程是否仍存在。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows 的 os.kill(pid, 0) 可能调用 TerminateProcess，不能用于只读探测。
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class _TriggerLock:
    """使用独占文件锁阻止两个监控进程同时处理同一交付包。"""

    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    def __enter__(self) -> "_TriggerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                lock_payload = _load_json(self.path)
                lock_pid = int(lock_payload.get("pid", 0))
            except (ValueError, TypeError):
                lock_pid = 0
            if _pid_is_running(lock_pid):
                return self
            # 新建锁在写入 PID 的极短窗口内可能还是空文件，保守视为占用。
            if lock_pid == 0 and time.time() - self.path.stat().st_mtime < 60:
                return self
            self.path.unlink()
        try:
            descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return self
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "acquired_at_utc": _utc_now()}, ensure_ascii=False))
        self.acquired = True
        return self

    def __exit__(self, *_: object) -> None:
        if self.acquired and self.path.exists():
            self.path.unlink()


def _load_state(path: Path) -> Dict[str, Any]:
    """读取处理账本；首次运行返回空账本。"""
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "deliveries": {}}
    payload = _load_json(path)
    if not isinstance(payload.get("deliveries"), dict):
        raise ValueError(f"触发状态账本格式错误：{path}")
    return payload


def _freeze_snapshot(validation: Dict[str, Any], snapshot_dir: Path) -> None:
    """按已核验清单复制不可混用的输入快照。"""
    if snapshot_dir.exists():
        validate_delivery(snapshot_dir, validation["marker_path"].name)
        return
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = snapshot_dir.with_name(f".{snapshot_dir.name}.{os.getpid()}.tmp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    try:
        for relative, source in validation["actual_files"].items():
            target = temp_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copy2(validation["marker_path"], temp_dir / validation["marker_path"].name)
        # 临时快照通过二次核验后才原子改名为正式快照。
        validate_delivery(temp_dir, validation["marker_path"].name)
        temp_dir.replace(snapshot_dir)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def process_delivery_once(
    package_dir: Path,
    output_root: Path,
    *,
    marker_name: str = MARKER_NAME,
    retry: bool = False,
    suite_runner: Callable[..., Dict[str, Any]] = run_formal_experiment_suite,
    readiness_runner: Callable[..., Dict[str, Any]] = run_readiness_pipeline,
) -> Dict[str, Any]:
    """处理一次到件；重复内容直接返回，不再次运行算法。"""
    package_dir, output_root = Path(package_dir), Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    latest_path = output_root / LATEST_SUMMARY_NAME
    try:
        validation = validate_delivery(package_dir, marker_name)
    except FileNotFoundError as exc:
        summary = {"status": "waiting", "processed": False, "message": str(exc), "checked_at_utc": _utc_now()}
        _write_json_atomic(latest_path, summary)
        return summary
    except Exception as exc:
        summary = {"status": "invalid", "processed": False, "message": str(exc), "checked_at_utc": _utc_now()}
        _write_json_atomic(latest_path, summary)
        return summary

    marker = validation["marker"]
    fingerprint = validation["fingerprint"]
    state_path = output_root / STATE_NAME
    with _TriggerLock(output_root / ".official_data_trigger.lock") as lock:
        if not lock.acquired:
            summary = {
                "status": "busy",
                "processed": False,
                "delivery_id": marker["delivery_id"],
                "fingerprint": fingerprint,
                "message": f"另一个正式数据触发进程正在运行：{lock.path}",
                "checked_at_utc": _utc_now(),
            }
            _write_json_atomic(latest_path, summary)
            return summary
        state = _load_state(state_path)
        previous = state["deliveries"].get(fingerprint)
        if previous and not retry:
            summary = {
                "status": "duplicate",
                "processed": False,
                "delivery_id": marker["delivery_id"],
                "fingerprint": fingerprint,
                "previous_status": previous["status"],
                "previous_output": previous.get("run_root", ""),
                "checked_at_utc": _utc_now(),
            }
            _write_json_atomic(latest_path, summary)
            return summary

        attempts = int(previous.get("attempts", 0)) + 1 if previous else 1
        delivery_root = output_root / "deliveries" / f"{marker['delivery_id']}-{fingerprint[:12]}"
        snapshot_dir = delivery_root / "snapshot"
        run_root = delivery_root / "runs" / f"attempt_{attempts:03d}"
        record = {
            "delivery_id": marker["delivery_id"],
            "fingerprint": fingerprint,
            "status": "running",
            "attempts": attempts,
            "started_at_utc": _utc_now(),
            "snapshot_dir": str(snapshot_dir),
            "run_root": str(run_root),
        }
        state["deliveries"][fingerprint] = record
        state["updated_at_utc"] = _utc_now()
        _write_json_atomic(state_path, state)

        try:
            _freeze_snapshot(validation, snapshot_dir)
            refs = validation["references"]
            experiment = dict(marker.get("experiment", {}))
            if "calibration_summary" in refs:
                experiment["calibration_summary"] = snapshot_dir / refs["calibration_summary"]
            runtime_data = snapshot_dir / refs["data_dir"]
            source_data = snapshot_dir / refs["source_dir"]
            timetable = snapshot_dir / refs["timetable"]
            readiness = readiness_runner(
                runtime_data,
                source_data,
                timetable,
                run_root / "project_validation",
                run_simulation=True,
            )
            simulation = readiness.get("simulation")
            acceptance_passed = bool(readiness.get("accepted", False))
            simulation_passed = bool(
                simulation is not None
                and simulation.get("returncode") == 0
                and simulation.get("audit", {}).get("accepted", False)
            )
            suite: Dict[str, Any] = {}
            if not acceptance_passed:
                status = "blocked"
            elif not simulation_passed:
                status = "failed"
            else:
                suite = suite_runner(
                    data_dir=runtime_data,
                    source_dir=source_data,
                    timetable=timetable,
                    output_root=run_root / "formal_experiment",
                    window_id=marker["window_id"],
                    **experiment,
                )
                status = str(suite.get("status", "failed"))
                if status not in {"completed", "blocked", "failed"}:
                    status = "failed"
            message = "正式实验已完成。" if status == "completed" else (
                "正式数据或校准门禁未通过，未发布正式结论。" if status == "blocked" else "正式实验执行失败。"
            )
            record.update({
                "status": status,
                "finished_at_utc": _utc_now(),
                "message": message,
                "project_validation_accepted": acceptance_passed,
                "project_simulation_passed": simulation_passed,
                "formal_experiment_status": suite.get("status"),
                "formal_data_accepted": suite.get("readiness", {}).get("accepted", acceptance_passed),
            })
        except Exception as exc:
            record.update({"status": "failed", "finished_at_utc": _utc_now(), "message": str(exc)})

        state["deliveries"][fingerprint] = record
        state["updated_at_utc"] = _utc_now()
        _write_json_atomic(state_path, state)
        summary = {**record, "processed": True}
        _write_json_atomic(run_root / "trigger_summary.json", summary)
        _write_json_atomic(latest_path, summary)
        return summary


def watch_deliveries(
    package_dir: Path,
    output_root: Path,
    *,
    marker_name: str = MARKER_NAME,
    poll_seconds: float = 30.0,
) -> int:
    """持续轮询到件标记；内容未变化时仅返回重复状态，不重复计算。"""
    if poll_seconds <= 0:
        raise ValueError("poll_seconds 必须大于0。")
    print(f"正在监控正式数据目录：{package_dir}；轮询间隔 {poll_seconds:g} 秒。按 Ctrl+C 停止。")
    last_signature = ""
    try:
        while True:
            marker_path = Path(package_dir) / marker_name
            signature = _sha256(marker_path) if marker_path.is_file() else "missing"
            if signature != last_signature:
                result = process_delivery_once(package_dir, output_root, marker_name=marker_name)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                last_signature = signature
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("正式数据监控已停止。")
        return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """提供生成标记、单次检查和常驻监控三个操作。"""
    parser = argparse.ArgumentParser(description="正式数据到件自动触发器")
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("outputs") / "official_data_auto_trigger")
    parser.add_argument("--marker-name", default=MARKER_NAME)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args(argv)
    if args.watch:
        return watch_deliveries(
            args.package_dir, args.output_root, marker_name=args.marker_name, poll_seconds=args.poll_seconds
        )
    result = process_delivery_once(
        args.package_dir, args.output_root, marker_name=args.marker_name, retry=args.retry
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"completed": 0, "duplicate": 0, "waiting": 0, "blocked": 2}.get(result["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
