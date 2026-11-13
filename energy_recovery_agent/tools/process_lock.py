"""提供带所有者令牌的跨进程文件互斥锁。"""

from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ProcessLock:
    """使用排他创建避免维护或发布任务并发写同一目标。"""

    def __init__(self, path: Path, purpose: str) -> None:
        self.path = path
        self.purpose = purpose
        self.token = uuid.uuid4().hex
        self.acquired = False

    def __enter__(self) -> "ProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0", "purpose": self.purpose, "pid": os.getpid(),
            "host": socket.gethostname(), "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "owner_token": self.token,
        }
        try:
            descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            owner = self.path.read_text(encoding="utf-8", errors="replace") if self.path.is_file() else "unknown"
            raise RuntimeError(f"已有任务持有锁：{self.path}\n{owner}") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self.acquired or not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("owner_token") == self.token:
            self.path.unlink()
        self.acquired = False

