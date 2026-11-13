-- 车载传感器原始遥测与路段能耗汇总。
-- 原始层按列车和采集时刻幂等写入，默认采样周期为 30 秒。
SET NAMES utf8mb4;
USE carbon_emissions;

CREATE TABLE IF NOT EXISTS energy_train_telemetry (
    telemetry_id bigint NOT NULL AUTO_INCREMENT,
    version_id char(36) NOT NULL,
    segment_id char(36) DEFAULT NULL,
    train_code varchar(64) NOT NULL,
    observed_at datetime(3) NOT NULL,
    direction varchar(16) NOT NULL DEFAULT 'forward',
    longitude decimal(10,7) DEFAULT NULL,
    latitude decimal(10,7) DEFAULT NULL,
    speed_kmh decimal(10,3) DEFAULT NULL,
    acceleration_ms2 decimal(10,5) DEFAULT NULL,
    gradient_permille decimal(10,4) DEFAULT NULL,
    traction_meter_kwh decimal(18,6) DEFAULT NULL,
    regenerative_meter_kwh decimal(18,6) DEFAULT NULL,
    interval_traction_kwh decimal(18,6) DEFAULT NULL,
    interval_regenerative_kwh decimal(18,6) DEFAULT NULL,
    quality_status varchar(24) NOT NULL DEFAULT 'valid',
    raw_payload json DEFAULT NULL,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (telemetry_id),
    UNIQUE KEY uk_energy_telemetry_train_time (version_id, train_code, observed_at),
    KEY idx_energy_telemetry_segment_time (segment_id, observed_at),
    CONSTRAINT ck_energy_telemetry_direction CHECK (direction IN ('forward', 'reverse')),
    CONSTRAINT ck_energy_telemetry_quality CHECK (quality_status IN ('valid', 'suspect', 'invalid'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='车载传感器周期遥测数据';

CREATE TABLE IF NOT EXISTS energy_segment_consumption_summary (
    summary_id bigint NOT NULL AUTO_INCREMENT,
    version_id char(36) NOT NULL,
    segment_id char(36) NOT NULL,
    window_start datetime NOT NULL,
    window_end datetime NOT NULL,
    direction varchar(16) NOT NULL DEFAULT 'both',
    train_count int NOT NULL DEFAULT 0,
    sample_count int NOT NULL DEFAULT 0,
    traction_consumption_kwh decimal(18,6) NOT NULL DEFAULT 0,
    regenerative_energy_kwh decimal(18,6) NOT NULL DEFAULT 0,
    net_energy_kwh decimal(18,6) NOT NULL DEFAULT 0,
    distance_train_km decimal(18,6) NOT NULL DEFAULT 0,
    energy_intensity_kwh_per_train_km decimal(18,6) DEFAULT NULL,
    energy_level varchar(16) NOT NULL DEFAULT 'medium',
    source_type varchar(24) NOT NULL DEFAULT 'sensor_aggregate',
    algorithm_version varchar(32) NOT NULL DEFAULT '1.0',
    generated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (summary_id),
    UNIQUE KEY uk_energy_segment_summary_window
        (version_id, segment_id, window_start, window_end, direction),
    KEY idx_energy_segment_summary_level_time (energy_level, window_end),
    CONSTRAINT ck_energy_segment_summary_window CHECK (window_end > window_start),
    CONSTRAINT ck_energy_segment_summary_direction CHECK (direction IN ('forward', 'reverse', 'both')),
    CONSTRAINT ck_energy_segment_summary_level CHECK (energy_level IN ('low', 'medium', 'high')),
    CONSTRAINT ck_energy_segment_summary_source CHECK (source_type IN ('sensor_aggregate', 'import', 'demo'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='供大屏和统计查询使用的路段能耗汇总';

-- 传感器接入前提供可识别的演示汇总，source_type=demo 可与正式数据区分。
INSERT INTO energy_segment_consumption_summary
    (version_id, segment_id, window_start, window_end, direction, train_count, sample_count,
     traction_consumption_kwh, regenerative_energy_kwh, net_energy_kwh, distance_train_km,
     energy_intensity_kwh_per_train_km, energy_level, source_type, algorithm_version)
SELECT ranked.version_id, ranked.segment_id, '2026-09-01 00:00:00', '2026-09-30 23:59:59', 'both',
       12 + MOD(ranked.seq, 9), 480 + ranked.seq * 17,
       ROUND(720 + ranked.seq * 41.5, 6), ROUND(90 + MOD(ranked.seq, 5) * 13.5, 6),
       ROUND((720 + ranked.seq * 41.5) - (90 + MOD(ranked.seq, 5) * 13.5), 6),
       ROUND((12 + MOD(ranked.seq, 9)) * (ranked.end_km - ranked.start_km), 6),
       ROUND(((720 + ranked.seq * 41.5) - (90 + MOD(ranked.seq, 5) * 13.5)) /
             NULLIF((12 + MOD(ranked.seq, 9)) * (ranked.end_km - ranked.start_km), 0), 6),
       CASE WHEN MOD(ranked.seq, 3) = 0 THEN 'high'
            WHEN MOD(ranked.seq, 3) = 1 THEN 'medium' ELSE 'low' END,
       'demo', 'demo-1.0'
FROM (
    SELECT s.version_id, s.segment_id, s.start_km, s.end_km,
           ROW_NUMBER() OVER (ORDER BY s.start_km, s.segment_code) AS seq
    FROM energy_route_segment s
    JOIN energy_project_version v ON v.version_id = s.version_id
    JOIN energy_project p ON p.project_id = v.project_id
    WHERE p.project_code = 'shuohuang_demo' AND v.version_code = 'v1'
    ORDER BY s.start_km, s.segment_code
    LIMIT 24
) ranked
ON DUPLICATE KEY UPDATE
    train_count = VALUES(train_count), sample_count = VALUES(sample_count),
    traction_consumption_kwh = VALUES(traction_consumption_kwh),
    regenerative_energy_kwh = VALUES(regenerative_energy_kwh),
    net_energy_kwh = VALUES(net_energy_kwh), distance_train_km = VALUES(distance_train_km),
    energy_intensity_kwh_per_train_km = VALUES(energy_intensity_kwh_per_train_km),
    energy_level = VALUES(energy_level), source_type = VALUES(source_type),
    algorithm_version = VALUES(algorithm_version), generated_at = CURRENT_TIMESTAMP;
