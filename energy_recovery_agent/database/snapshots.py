"""不可变输入快照与结果工件的无损文件封装。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping
import json
import mimetypes


@dataclass(frozen=True)
class FileRecord:
    """数据库中一个文件工件的稳定表示。"""

    relative_path: str
    media_type: str
    content: bytes
    content_sha256: str

    @property
    def content_size_bytes(self) -> int:
        return len(self.content)


def validate_relative_path(value: str) -> str:
    """拒绝绝对路径和目录穿越，返回统一POSIX相对路径。"""

    text = str(value).replace("\\", "/").strip()
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"非法数据库工件相对路径：{value!r}")
    return path.as_posix()


def media_type_for_path(path: Path | str) -> str:
    """根据文件名给出稳定媒体类型。"""

    media_type, _encoding = mimetypes.guess_type(str(path))
    if media_type:
        return media_type
    suffix = Path(str(path)).suffix.lower()
    return {
        ".csv": "text/csv",
        ".json": "application/json",
        ".md": "text/markdown",
    }.get(suffix, "application/octet-stream")


def record_from_bytes(relative_path: str, content: bytes) -> FileRecord:
    """从字节构造带哈希的文件记录。"""

    normalized = validate_relative_path(relative_path)
    payload = bytes(content)
    return FileRecord(
        relative_path=normalized,
        media_type=media_type_for_path(normalized),
        content=payload,
        content_sha256=sha256(payload).hexdigest(),
    )


def collect_file_records(source_dir: Path) -> tuple[FileRecord, ...]:
    """按相对路径排序读取目录，形成无损、确定性的文件记录。"""

    root = Path(source_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"输入数据目录不存在：{root}")
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative_path = path.relative_to(root).as_posix()
        records.append(record_from_bytes(relative_path, path.read_bytes()))
    if not records:
        raise ValueError(f"输入数据目录没有文件：{root}")
    return tuple(records)


def snapshot_manifest(records: Iterable[FileRecord]) -> dict:
    """生成用于版本冻结和复核的文件清单及整体哈希。"""

    ordered = sorted(records, key=lambda item: item.relative_path)
    files = [
        {
            "relative_path": record.relative_path,
            "media_type": record.media_type,
            "content_size_bytes": record.content_size_bytes,
            "content_sha256": record.content_sha256,
        }
        for record in ordered
    ]
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "1.0",
        "file_count": len(files),
        "files": files,
        "snapshot_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def materialize_file_records(records: Iterable[FileRecord], destination: Path) -> dict:
    """将数据库文件记录安全还原到隔离目录，并逐项校验哈希。"""

    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    normalized_records = tuple(records)
    seen = set()
    for record in normalized_records:
        relative_path = validate_relative_path(record.relative_path)
        if relative_path in seen:
            raise ValueError(f"数据库快照包含重复路径：{relative_path}")
        seen.add(relative_path)
        digest = sha256(record.content).hexdigest()
        if digest != record.content_sha256:
            raise ValueError(f"数据库快照文件哈希不一致：{relative_path}")
        target = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"数据库快照路径越界：{relative_path}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(record.content)
    return snapshot_manifest(normalized_records)


def merge_file_records(
    base_records: Iterable[FileRecord],
    extra_files: Mapping[str, Path],
) -> tuple[FileRecord, ...]:
    """将平台额外文件按逻辑路径并入版本快照，重复路径由额外文件显式覆盖。"""

    by_path = {record.relative_path: record for record in base_records}
    for logical_path, source_path in extra_files.items():
        path = Path(source_path)
        if not path.is_file():
            raise FileNotFoundError(f"额外输入文件不存在：{path}")
        record = record_from_bytes(logical_path, path.read_bytes())
        by_path[record.relative_path] = record
    return tuple(by_path[key] for key in sorted(by_path))

