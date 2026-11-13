"""Run named business CLIs without installing Python in the Java container.

Only the application container may call this service. Files are exchanged through
the same shared directory mounted at the same absolute path in both containers.
No shell or caller-supplied executable/module is accepted.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

CODE_ROOT = Path(os.getenv("PYTHON_CODE_ROOT", "/opt/shsystem")).resolve()
SHARED_ROOT = Path(os.getenv("SHARED_ROOT", "/srv/shared")).resolve()
TOKEN = os.getenv("PYTHON_INTERNAL_TOKEN", "")
ENV_KEYS = frozenset({
    "CARBON_REPORT_JOB_ASSETS_DIR", "MPLCONFIGDIR", "CARBON_REPORT_LLM_BASE_URL",
    "CARBON_REPORT_LLM_MODEL", "CARBON_REPORT_LLM_API_KEY", "OPENAI_API_KEY",
    "SINGLE_TRAIN_RESULT_ROOT", "SINGLE_TRAIN_SOLVE_TIMEOUT",
})
TASKS = {
    "report": (CODE_ROOT, ["-m", "carbon_report_agent.cli"]),
    "markdown": (CODE_ROOT, ["-m", "carbon_report_agent.markdown_export"]),
    "energy": (CODE_ROOT / "energy_recovery_agent", ["-m", "database.cli"]),
    "single-train": (CODE_ROOT, ["-m", "single_train_recovery_agent.cli"]),
    "steam": (CODE_ROOT, [str(CODE_ROOT / "steam_calculator.py")]),
}
# Keep control operations available while solvers are running.
SLOTS = threading.BoundedSemaphore(4)
SOLVER_SLOTS = threading.BoundedSemaphore(2)
TASK_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="python-task")
TASKS_LOCK = threading.RLock()
TASKS_STATE: dict[str, dict[str, Any]] = {}
TASK_PROCESSES: dict[str, subprocess.Popen] = {}


def authorize(authorization: str = Header(default="")) -> None:
    if len(TOKEN) < 32:
        raise HTTPException(503, "Python service token is not configured")
    if not hmac.compare_digest(authorization, "Bearer " + TOKEN):
        raise HTTPException(401, "Invalid internal token")


class RunRequest(BaseModel):
    task: Literal["report", "markdown", "energy", "single-train", "steam"]
    args: list[str] = Field(default_factory=list, max_length=256)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict, max_length=8)
    timeoutSeconds: int = Field(default=300, ge=1, le=7500)
    maxOutputBytes: int = Field(default=1048576, ge=1024, le=16777216)


class TaskRequest(RunRequest):
    """Asynchronous version of RunRequest used by long-running business jobs."""
    idempotencyKey: str | None = Field(default=None, max_length=128)


def shared_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise HTTPException(400, "An absolute shared path is required")
    path = path.resolve()
    if not path.is_relative_to(SHARED_ROOT):
        raise HTTPException(400, "Path is outside the shared directory")
    return path


def command_for(req: RunRequest) -> tuple[list[str], Path, dict[str, str]]:
    root, fixed_args = TASKS[req.task]
    if any("\0" in arg or len(arg) > 32768 for arg in req.args):
        raise HTTPException(400, "Invalid argument")
    # Administrative schema/security CLIs are deployment operations, not API calls.
    if req.task == "energy" and (not req.args or req.args[0].startswith("-")
                                  or req.args[0] in {"bootstrap", "migrate", "apply-security"}):
        raise HTTPException(400, "Administrative operations are not exposed")
    if set(req.env) - ENV_KEYS:
        raise HTTPException(400, "Unsupported environment override")
    env = os.environ.copy()
    env.update(req.env)
    env.update(PYTHONPATH=str(root), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    for name in ("CARBON_REPORT_JOB_ASSETS_DIR", "MPLCONFIGDIR"):
        if name in req.env:
            shared_path(req.env[name])
    for name in ("SINGLE_TRAIN_RESULT_ROOT",):
        if req.env.get(name):
            shared_path(req.env[name])
    # Every path accepted by the current CLI contract must live in the shared volume.
    path_flags = {"--input", "--output", "--input-docx", "--manifest", "--input-dir",
                  "--output-dir", "--source-dir", "--excel-dir", "--excel-file",
                  "--parameters-file", "--tables-file", "--input-file"}
    for index, arg in enumerate(req.args):
        flag, sep, inline = arg.partition("=")
        if flag in path_flags or flag == "--extra-file":
            if not sep and index + 1 >= len(req.args):
                raise HTTPException(400, "Missing file argument")
            value = inline if sep else req.args[index + 1]
            if flag == "--extra-file":
                value = value.partition("=")[2]
            shared_path(value)
    cwd = shared_path(req.cwd) if req.cwd else root
    if not cwd.is_dir():
        raise HTTPException(400, "Working directory does not exist")
    return [sys.executable, *fixed_args, *req.args], cwd, env


def run_child(command: list[str], cwd: Path, env: dict[str, str],
              timeout: int, limit: int, task_id: str | None = None) -> dict:
    buffers = [bytearray(), bytearray()]
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=os.name != "nt")
    if task_id:
        with TASKS_LOCK:
            TASK_PROCESSES[task_id] = proc

    def drain(stream, target):
        with stream:
            while chunk := stream.read(65536):
                remaining = max(0, limit - len(target))
                target.extend(chunk[:remaining])

    readers = [threading.Thread(target=drain, args=(stream, target), daemon=True)
               for stream, target in zip((proc.stdout, proc.stderr), buffers)]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        # Also kill descendants that outlive a completed CLI (e.g. LibreOffice).
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif proc.poll() is None:
            proc.kill()
        proc.wait()
        for reader in readers:
            reader.join(timeout=5)
        if task_id:
            with TASKS_LOCK:
                TASK_PROCESSES.pop(task_id, None)
    return {"exitCode": proc.returncode, "stdout": buffers[0].decode("utf-8", "replace"),
            "stderr": buffers[1].decode("utf-8", "replace"), "timedOut": timed_out}


app = FastAPI(title="Internal Python business service", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    if len(TOKEN) < 32:
        raise HTTPException(503, "Python service token is not configured")
    return {"status": "ok"}


@app.get("/v1/capabilities", dependencies=[Depends(authorize)])
def capabilities():
    return {"report": (CODE_ROOT / "carbon_report_agent/cli.py").is_file(),
            "steam": (CODE_ROOT / "steam_calculator.py").is_file(),
            "pdf": bool(shutil.which("libreoffice") or shutil.which("soffice")),
            "sharedDirectory": SHARED_ROOT.is_dir()}


@app.post("/v1/run", dependencies=[Depends(authorize)])
def run(req: RunRequest):
    command, cwd, env = command_for(req)
    solver = (req.task == "energy" and req.args[0] == "worker-once") or (
        req.task == "single-train" and req.args and req.args[0] == "work")
    if solver and not SOLVER_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Solver capacity is full; retry later")
    acquired = SLOTS.acquire(blocking=False)
    try:
        if not acquired:
            raise HTTPException(429, "Python service is busy; retry later")
        return run_child(command, cwd, env, req.timeoutSeconds, req.maxOutputBytes)
    finally:
        if acquired:
            SLOTS.release()
        if solver:
            SOLVER_SLOTS.release()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_worker(task_id: str, req: TaskRequest, command: list[str], cwd: Path,
                 env: dict[str, str]) -> None:
    with TASKS_LOCK:
        TASKS_STATE[task_id].update(status="running", startedAt=_now())
    solver = (req.task == "energy" and req.args and req.args[0] == "worker-once") or (
        req.task == "single-train" and req.args and req.args[0] == "work")
    acquired = SLOTS.acquire(blocking=False)
    solver_acquired = SOLVER_SLOTS.acquire(blocking=False) if solver else True
    try:
        if not acquired or not solver_acquired:
            result = {"exitCode": 75, "stdout": "", "stderr": "task capacity is full", "timedOut": False}
        else:
            result = run_child(command, cwd, env, req.timeoutSeconds, req.maxOutputBytes, task_id)
        with TASKS_LOCK:
            current = TASKS_STATE.get(task_id)
            if current and current.get("status") != "cancelled":
                current.update(status="succeeded" if result["exitCode"] == 0 and not result["timedOut"] else "failed",
                               finishedAt=_now(), result=result)
    except Exception as exc:
        with TASKS_LOCK:
            if task_id in TASKS_STATE:
                TASKS_STATE[task_id].update(status="failed", finishedAt=_now(),
                                            result={"exitCode": 1, "stdout": "", "stderr": str(exc), "timedOut": False})
    finally:
        if acquired:
            SLOTS.release()
        if solver and solver_acquired:
            SOLVER_SLOTS.release()


@app.post("/v1/tasks", dependencies=[Depends(authorize)], status_code=202)
def submit_task(req: TaskRequest):
    command, cwd, env = command_for(req)
    with TASKS_LOCK:
        if req.idempotencyKey:
            for existing in TASKS_STATE.values():
                if existing.get("idempotencyKey") == req.idempotencyKey:
                    return {"taskId": existing["taskId"], "status": existing["status"], "deduplicated": True}
        task_id = uuid.uuid4().hex
        TASKS_STATE[task_id] = {"taskId": task_id, "task": req.task, "status": "queued",
                                "idempotencyKey": req.idempotencyKey, "createdAt": _now()}
    TASK_EXECUTOR.submit(_task_worker, task_id, req, command, cwd, env)
    return {"taskId": task_id, "status": "queued", "deduplicated": False}


@app.get("/v1/tasks/{task_id}", dependencies=[Depends(authorize)])
def get_task(task_id: str):
    with TASKS_LOCK:
        task = TASKS_STATE.get(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return dict(task)


@app.delete("/v1/tasks/{task_id}", dependencies=[Depends(authorize)])
def cancel_task(task_id: str):
    with TASKS_LOCK:
        task = TASKS_STATE.get(task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task["status"] in {"succeeded", "failed", "cancelled"}:
            return dict(task)
        task["status"] = "cancelled"
        task["finishedAt"] = _now()
        proc = TASK_PROCESSES.get(task_id)
    if proc and proc.poll() is None:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()
    return {"taskId": task_id, "status": "cancelled"}
