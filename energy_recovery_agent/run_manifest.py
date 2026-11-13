"""Run-level reproducibility manifests for the unified project entry point.

This module records execution metadata without changing algorithm inputs or
outputs.  A manifest is written once before a command starts (``running``) and
updated when the command finishes with its return code and validation status.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence


SCHEMA_VERSION = "1.1"

INPUT_PATH_ATTRIBUTES = (
    ("data_dir", "runtime_data"),
    ("resource_data_dir", "resource_data"),
    ("source_dir", "reviewed_source"),
    ("smart_meter_dir", "smart_meter_source"),
    ("timetable", "timetable"),
    ("station_csv", "station_table"),
    ("factor_json", "calibration_factors"),
    ("power_arm_path", "power_arm_table"),
    ("input", "input_bundle"),
    ("inbox_dir", "official_inbox"),
    ("template_dir", "official_template"),
    ("status_json", "intake_status"),
    ("route_metadata", "route_metadata"),
)

OUTPUT_PATH_ATTRIBUTES = (
    "output_root",
    "output_dir",
    "output_csv",
    "alignment_output_dir",
)

SKIPPED_DIRECTORY_NAMES = {".git", ".venv", "venv", "env", "__pycache__"}
CODE_EXCLUDED_DIRECTORY_NAMES = SKIPPED_DIRECTORY_NAMES | {"data", "outputs", "shuohuang_data"}


def _utc_now() -> datetime:
    """函数 _utc_now：执行该模块中的相关处理逻辑。"""
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    """函数 _utc_text：执行该模块中的相关处理逻辑。"""
    return value.astimezone(timezone.utc).isoformat()


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """函数 _sha256：执行该模块中的相关处理逻辑。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: object, project_root: Path) -> Optional[Path]:
    """函数 _resolve_path：执行该模块中的相关处理逻辑。"""
    if value is None or value == "":
        return None
    try:
        path = Path(value)
    except (TypeError, ValueError):
        return None
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _display_path(path: Path, project_root: Path) -> str:
    """函数 _display_path：执行该模块中的相关处理逻辑。"""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def _iter_input_files(path: Path) -> Iterable[Path]:
    """函数 _iter_input_files：执行该模块中的相关处理逻辑。"""
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        return
    for current, dirs, files in os.walk(path):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in SKIPPED_DIRECTORY_NAMES]
        for name in files:
            candidate = current_path / name
            try:
                if candidate.is_file():
                    yield candidate
            except OSError:
                continue


def _serialize_argument(value: object) -> object:
    """函数 _serialize_argument：执行该模块中的相关处理逻辑。"""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_argument(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_argument(item) for key, item in value.items()}
    if callable(value):
        return f"{getattr(value, '__module__', '')}.{getattr(value, '__qualname__', repr(value))}"
    return repr(value)


def serialize_arguments(args: object) -> dict[str, object]:
    """函数 serialize_arguments：执行该模块中的相关处理逻辑。"""
    values = vars(args) if hasattr(args, "__dict__") else {}
    return {
        str(key): _serialize_argument(value)
        for key, value in values.items()
        if key != "func"
    }


def _stable_json_hash(value: object) -> str:
    """Hash a JSON-compatible value with stable key ordering."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _find_seed_values(value: object, path: str = "") -> dict[str, object]:
    """Extract explicit random-seed arguments without guessing defaults."""

    found: dict[str, object] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text.lower() in {"seed", "random_seed", "numpy_seed"}:
                if isinstance(child, (int, float, str)) and not isinstance(child, bool):
                    found[child_path] = child
            found.update(_find_seed_values(child, child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.update(_find_seed_values(child, f"{path}[{index}]"))
    return found


def collect_environment() -> dict[str, object]:
    """Capture platform and installed dependency versions for reruns."""

    packages = ("numpy", "pandas", "openpyxl", "matplotlib", "scipy", "networkx", "pytest")
    versions: dict[str, Optional[str]] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "platform": platform.platform(),
        "os_name": os.name,
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": sys.executable,
        "dependencies": versions,
    }


def collect_input_inventory(args: object, project_root: Path) -> dict[str, object]:
    """函数 collect_input_inventory：执行该模块中的相关处理逻辑。"""
    roots: list[dict[str, object]] = []
    by_file: dict[str, dict[str, object]] = {}
    for attribute, role in INPUT_PATH_ATTRIBUTES:
        if not hasattr(args, attribute):
            continue
        path = _resolve_path(getattr(args, attribute), project_root)
        if path is None:
            continue
        root_record = {
            "argument": attribute,
            "role": role,
            "path": _display_path(path, project_root),
            "exists": path.exists(),
            "kind": "file" if path.is_file() else "directory" if path.is_dir() else "missing",
        }
        roots.append(root_record)
        for file_path in _iter_input_files(path):
            try:
                key = str(file_path.resolve())
                stat = file_path.stat()
                record = by_file.setdefault(
                    key,
                    {
                        "path": _display_path(file_path.resolve(), project_root),
                        "roles": [],
                        "size_bytes": stat.st_size,
                        "modified_utc": _utc_text(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
                        "sha256": _sha256(file_path),
                    },
                )
                if role not in record["roles"]:
                    record["roles"].append(role)
            except (OSError, PermissionError):
                continue
    for record in by_file.values():
        record["roles"] = sorted(record["roles"])
    return {
        "roots": sorted(roots, key=lambda item: (str(item["argument"]), str(item["path"]))),
        "files": sorted(by_file.values(), key=lambda item: str(item["path"])),
        "hash_algorithm": "sha256",
        "capture": "before_execution",
    }


def collect_data_status(args: object, project_root: Path) -> list[dict[str, object]]:
    """函数 collect_data_status：执行该模块中的相关处理逻辑。"""
    statuses: list[dict[str, object]] = []
    seen: set[Path] = set()
    for attribute in ("data_dir", "resource_data_dir"):
        if not hasattr(args, attribute):
            continue
        data_dir = _resolve_path(getattr(args, attribute), project_root)
        if data_dir is None or not data_dir.is_dir() or data_dir in seen:
            continue
        seen.add(data_dir)
        status: dict[str, object] = {
            "argument": attribute,
            "path": _display_path(data_dir, project_root),
            "data_status": None,
            "route_length_km": None,
            "explicit_assumption_count": None,
            "needs_confirmation_count": None,
            "build_summary": None,
        }
        route_path = data_dir / "route_metadata.json"
        try:
            route = json.loads(route_path.read_text(encoding="utf-8"))
            status["data_status"] = route.get("data_status")
            route_info = route.get("route", {})
            if isinstance(route_info, dict):
                status["route_length_km"] = route_info.get("total_length_km")
            source_info = route.get("source_metadata", {})
            if isinstance(source_info, dict):
                assumptions = source_info.get("explicit_assumptions", [])
                confirmations = source_info.get("needs_confirmation", [])
                status["explicit_assumption_count"] = len(assumptions) if isinstance(assumptions, list) else None
                status["needs_confirmation_count"] = len(confirmations) if isinstance(confirmations, list) else None
        except (OSError, ValueError, TypeError):
            status["route_metadata_error"] = "unavailable_or_invalid"
        build_path = data_dir / "build_summary.json"
        try:
            status["build_summary"] = json.loads(build_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            status["build_summary"] = None
        statuses.append(status)
    return statuses


def collect_output_paths(args: object, project_root: Path) -> list[dict[str, str]]:
    """函数 collect_output_paths：执行该模块中的相关处理逻辑。"""
    paths: list[dict[str, str]] = []
    for attribute in OUTPUT_PATH_ATTRIBUTES:
        if not hasattr(args, attribute):
            continue
        path = _resolve_path(getattr(args, attribute), project_root)
        if path is not None:
            paths.append({"argument": attribute, "path": _display_path(path, project_root)})
    return paths


def collect_output_inventory(
    args: object,
    project_root: Path,
    started_at: Optional[datetime] = None,
) -> dict[str, object]:
    """Hash output files produced/updated by this run.

    ``output_root`` commonly points at the shared ``outputs/`` directory.  To
    avoid hashing historical artifacts on every invocation, directory scans
    only include files modified at or after the run start (with a small clock
    skew allowance).  Manifest and archive directories are always excluded.
    """

    roots = collect_output_paths(args, project_root)
    cutoff = started_at.timestamp() - 2.0 if started_at is not None else None
    excluded_names = {"run_manifests", "archive"}
    by_path: dict[str, dict[str, object]] = {}
    for item in roots:
        path = _resolve_path(item["path"], project_root)
        if path is None:
            continue
        candidates: Iterable[Path]
        if path.is_file():
            candidates = (path,)
        elif path.is_dir():
            discovered: list[Path] = []
            for current, dirs, files in os.walk(path):
                dirs[:] = [
                    name
                    for name in dirs
                    if name not in SKIPPED_DIRECTORY_NAMES and name not in excluded_names
                ]
                discovered.extend(Path(current) / name for name in files)
            candidates = discovered
        else:
            continue
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                stat = candidate.stat()
                if cutoff is not None and stat.st_mtime < cutoff:
                    continue
                relative = _display_path(candidate.resolve(), project_root)
                if relative.startswith("outputs/run_manifests/") or relative.startswith("outputs/archive/"):
                    continue
                by_path[relative] = {
                    "path": relative,
                    "size_bytes": stat.st_size,
                    "modified_utc": _utc_text(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
                    "sha256": _sha256(candidate),
                }
            except (OSError, PermissionError):
                continue
    files = sorted(by_path.values(), key=lambda item: str(item["path"]))
    digest = hashlib.sha256()
    for item in files:
        digest.update(str(item["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return {
        "roots": roots,
        "files": files,
        "file_count": len(files),
        "snapshot_sha256": digest.hexdigest(),
        "hash_algorithm": "sha256",
        "capture": "after_execution",
        "modified_since_utc": _utc_text(datetime.fromtimestamp(cutoff, timezone.utc)) if cutoff is not None else None,
    }


def _code_files(project_root: Path) -> list[Path]:
    """函数 _code_files：执行该模块中的相关处理逻辑。"""
    files: list[Path] = []
    for current, dirs, names in os.walk(project_root):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in CODE_EXCLUDED_DIRECTORY_NAMES]
        for name in names:
            path = current_path / name
            if path.suffix.lower() == ".py" and path.is_file():
                files.append(path)
    return sorted(files)


def collect_code_version(project_root: Path) -> dict[str, object]:
    """函数 collect_code_version：执行该模块中的相关处理逻辑。"""
    records: list[dict[str, str]] = []
    digest = hashlib.sha256()
    for path in _code_files(project_root):
        try:
            relative = _display_path(path.resolve(), project_root)
            file_hash = _sha256(path)
        except (OSError, PermissionError):
            continue
        records.append({"path": relative, "sha256": file_hash})
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")

    git_commit: Optional[str] = None
    git_dirty: Optional[bool] = None
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if commit.returncode == 0:
            git_commit = commit.stdout.strip() or None
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            git_dirty = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        pass

    return {
        "git_commit": git_commit,
        "git_worktree_dirty": git_dirty,
        "code_snapshot_sha256": digest.hexdigest(),
        "code_file_count": len(records),
        "code_files": records,
    }


def _manifest_directory(args: object, project_root: Path) -> Path:
    """函数 _manifest_directory：执行该模块中的相关处理逻辑。"""
    if hasattr(args, "output_root"):
        path = _resolve_path(getattr(args, "output_root"), project_root)
        if path is not None:
            return path / "run_manifests"
    if hasattr(args, "output_dir"):
        path = _resolve_path(getattr(args, "output_dir"), project_root)
        if path is not None:
            return path.parent / "run_manifests"
    if hasattr(args, "alignment_output_dir"):
        path = _resolve_path(getattr(args, "alignment_output_dir"), project_root)
        if path is not None:
            return path.parent / "run_manifests"
    return project_root / "outputs" / "run_manifests"


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    """函数 _write_json：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validation_candidates(args: object, project_root: Path) -> list[Path]:
    """函数 _validation_candidates：执行该模块中的相关处理逻辑。"""
    bases: list[Path] = []
    for item in collect_output_paths(args, project_root):
        path = project_root / item["path"] if not Path(item["path"]).is_absolute() else Path(item["path"])
        bases.append(path if path.is_dir() or path.suffix == "" else path.parent)
    candidates: list[Path] = []
    names = ("data_quality_summary.json", "summary.json", "audit_summary.json", "optimizer_summary.json")
    for base in bases:
        for name in names:
            candidates.append(base / name)
        candidates.append(base / "data_quality_validation" / "data_quality_summary.json")
    unique = sorted({path.resolve() for path in candidates})
    return [path for path in unique if path.is_file()]


def collect_validation_status(args: object, project_root: Path) -> dict[str, object]:
    """函数 collect_validation_status：执行该模块中的相关处理逻辑。"""
    reports: list[dict[str, object]] = []
    for path in _validation_candidates(args, project_root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        report = {
            "path": _display_path(path, project_root),
            "valid": payload.get("valid"),
            "error_count": payload.get("error_count"),
            "warning_count": payload.get("warning_count"),
            "status": payload.get("status"),
        }
        reports.append(report)
    data_quality = [report for report in reports if report["path"].endswith("data_quality_summary.json")]
    return {
        "status": "available" if reports else "not_available",
        "reports": reports,
        "data_quality": data_quality,
    }


def create_run_manifest(
    args: object,
    raw_argv: Sequence[str],
    project_root: Optional[Path] = None,
) -> dict[str, object]:
    """函数 create_run_manifest：执行该模块中的相关处理逻辑。"""
    root = (project_root or Path(__file__).resolve().parent).resolve()
    started = _utc_now()
    run_id = f"{started.strftime('%Y%m%dT%H%M%S.%fZ')}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    manifest_path = _manifest_directory(args, root) / f"run_{run_id}.json"
    arguments = serialize_arguments(args)
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "running",
        "started_at_utc": _utc_text(started),
        "ended_at_utc": None,
        "duration_s": None,
        "command": getattr(args, "command", None),
        "argv": list(raw_argv),
        "arguments": arguments,
        "arguments_sha256": _stable_json_hash(arguments),
        "random_seeds": _find_seed_values(arguments),
        "python": sys.version,
        "python_executable": sys.executable,
        "environment": collect_environment(),
        "working_directory": str(Path.cwd().resolve()),
        "project_root": str(root),
        "code_version": collect_code_version(root),
        "input_inventory": collect_input_inventory(args, root),
        "data_status": collect_data_status(args, root),
        "output_paths": collect_output_paths(args, root),
        "output_inventory": {
            "roots": collect_output_paths(args, root),
            "files": [],
            "file_count": 0,
            "snapshot_sha256": None,
            "hash_algorithm": "sha256",
            "capture": "pending_after_execution",
        },
        "validation_status": {"status": "pending", "reports": [], "data_quality": []},
        "input_hash_capture": "before_execution",
    }
    _write_json(manifest_path, manifest)
    return {"manifest_path": manifest_path, "manifest": manifest, "started": started, "project_root": root}


def finalize_run_manifest(
    context: Mapping[str, object],
    args: object,
    return_code: int,
    error: Optional[BaseException] = None,
) -> Path:
    """函数 finalize_run_manifest：执行该模块中的相关处理逻辑。"""
    manifest = dict(context["manifest"])
    started = context["started"]
    ended = _utc_now()
    if not isinstance(started, datetime):
        started = ended
    manifest["status"] = "failed" if error is not None or return_code != 0 else "success"
    manifest["ended_at_utc"] = _utc_text(ended)
    manifest["duration_s"] = round((ended - started).total_seconds(), 3)
    manifest["return_code"] = int(return_code)
    if error is not None:
        manifest["exception"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    project_root = context["project_root"]
    if not isinstance(project_root, Path):
        project_root = Path(project_root)
    manifest["validation_status"] = collect_validation_status(args, project_root)
    manifest["data_status_after"] = collect_data_status(args, project_root)
    manifest["output_inventory"] = collect_output_inventory(args, project_root, started_at=started)
    manifest_path = context["manifest_path"]
    if not isinstance(manifest_path, Path):
        manifest_path = Path(manifest_path)
    _write_json(manifest_path, manifest)
    return manifest_path
