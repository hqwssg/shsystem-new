"""数据集文件在库中用中文名存储，算法运行时再映射回英文名。"""

from __future__ import annotations

from typing import Iterable

from .snapshots import FileRecord, record_from_bytes, validate_relative_path

ENGLISH_TO_CHINESE = {
    "storage_candidate_sites.csv": "储能候选站点.csv",
    "storage_technologies.csv": "储能技术.csv",
    "storage_site_technology_options.csv": "储能站点技术配置.csv",
    "storage_planning_scenarios.json": "储能规划场景.json",
    "storage_planning_policy.json": "储能规划策略.json",
    "trains.csv": "列车参数.csv",
    "stations.csv": "车站.csv",
    "segments.csv": "区间.csv",
    "gradients.csv": "坡度.csv",
    "curves.csv": "曲线.csv",
    "battery.json": "储能参数.json",
    "energy_transfer_zones.csv": "储能区段.csv",
    "storage_devices.json": "储能设备.json",
    "power_arm_intervals.csv": "供电臂.csv",
    "signaling_blocks.csv": "闭塞.csv",
    "station_resources.csv": "车站能力.csv",
    "resource_config.json": "资源规则.json",
    "headway_constraints.csv": "追踪间隔.csv",
    "technical_operation_times.csv": "技术作业时分.csv",
    "technical_operation_times_out_of_scope.csv": "技术作业时分_范围外.csv",
    "station_operation_assignments.csv": "作业适用范围.csv",
    "operating_conditions.json": "作业条件.json",
    "route_metadata.json": "线路参数.json",
    "train_formation_modes_2025.csv": "编组模式.csv",
    "pdf_station_master.csv": "车站主数据.csv",
    "pdf_station_out_of_scope.csv": "车站_范围外.csv",
    "energy_calibration_factors.json": "能量标定.json",
    "smart_meter_calibration_samples.csv": "电表标定样本.csv",
    "smart_meter_calibration_samples_summary.json": "电表标定摘要.json",
    "smart_meter_representative_interval_samples.csv": "电表区间样本.csv",
    "build_summary.json": "构建摘要.json",
    "platform/running_diagram.xlsx": "platform/运行图.xlsx",
    "platform/timetable.csv": "platform/时刻表.csv",
    "platform/timetable.xlsx": "platform/时刻表.xlsx",
    "platform/historical_disturbance_replay.json": "platform/滚动扰动回放.json",
    "platform/joint_parameter_ranges.json": "platform/联合参数区间.json",
}

CHINESE_TO_ENGLISH = {chinese: english for english, chinese in ENGLISH_TO_CHINESE.items()}


def to_storage_path(relative_path: str) -> str:
    posix = validate_relative_path(relative_path)
    if posix in CHINESE_TO_ENGLISH:
        return posix
    return ENGLISH_TO_CHINESE.get(posix, posix)


def to_algorithm_path(relative_path: str) -> str:
    posix = str(relative_path or "").replace("\\", "/").strip()
    if not posix:
        return posix
    if posix in ENGLISH_TO_CHINESE:
        return posix
    return CHINESE_TO_ENGLISH.get(posix, posix)


def _remap_record(record: FileRecord, relative_path: str) -> FileRecord:
    if record.relative_path == relative_path:
        return record
    return record_from_bytes(relative_path, record.content)


def records_to_storage_names(records: Iterable[FileRecord]) -> tuple[FileRecord, ...]:
    by_path: dict[str, FileRecord] = {}
    for record in records:
        storage_path = to_storage_path(record.relative_path)
        by_path[storage_path] = _remap_record(record, storage_path)
    return tuple(sorted(by_path.values(), key=lambda item: item.relative_path))


def records_to_algorithm_names(records: Iterable[FileRecord]) -> tuple[FileRecord, ...]:
    remapped = [_remap_record(record, to_algorithm_path(record.relative_path)) for record in records]
    return tuple(sorted(remapped, key=lambda item: item.relative_path))


def migrate_dataset_file_names(connection) -> int:
    """把已入库的英文相对路径改成中文名。目标路径已存在则跳过，避免唯一约束冲突。"""

    from .mysql import transaction

    updated = 0
    with transaction(connection):
        with connection.cursor() as cursor:
            for english, chinese in ENGLISH_TO_CHINESE.items():
                cursor.execute(
                    """
                    UPDATE energy_dataset_file AS current_file
                    LEFT JOIN energy_dataset_file AS taken
                        ON taken.version_id = current_file.version_id
                       AND taken.relative_path = %s
                    SET current_file.relative_path = %s
                    WHERE current_file.relative_path = %s
                      AND taken.dataset_file_id IS NULL
                    """,
                    (chinese, chinese, english),
                )
                updated += cursor.rowcount or 0
    return updated
