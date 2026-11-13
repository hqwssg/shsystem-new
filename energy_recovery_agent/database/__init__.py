"""平台数据库集成组件。"""

from .snapshots import FileRecord, collect_file_records, materialize_file_records

__all__ = ["FileRecord", "collect_file_records", "materialize_file_records"]

