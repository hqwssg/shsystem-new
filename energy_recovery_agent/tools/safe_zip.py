"""提供带路径和资源上限的ZIP安全解压。"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path


DEFAULT_MAX_MEMBERS = 5000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


def safe_extract_zip(
    archive: zipfile.ZipFile,
    destination: Path,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> None:
    """校验全部成员后解压，避免路径穿越、符号链接和资源滥用。"""

    if max_members <= 0 or max_uncompressed_bytes <= 0:
        raise ValueError("ZIP解压上限必须为正数。")
    members = archive.infolist()
    if len(members) > max_members:
        raise ValueError(f"ZIP成员数超过上限：{len(members)} > {max_members}")
    total_size = sum(max(0, member.file_size) for member in members)
    if total_size > max_uncompressed_bytes:
        raise ValueError(f"ZIP解压后体积超过上限：{total_size} > {max_uncompressed_bytes}")

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for member in members:
        relative = Path(member.filename.replace("\\", "/"))
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError(f"ZIP成员路径不安全：{member.filename}")
        unix_mode = member.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise ValueError(f"ZIP成员不得为符号链接：{member.filename}")
        target = (destination / relative).resolve()
        try:
            target.relative_to(destination)
        except ValueError as exc:
            raise ValueError(f"ZIP成员越过目标目录：{member.filename}") from exc

    for member in members:
        archive.extract(member, destination)
