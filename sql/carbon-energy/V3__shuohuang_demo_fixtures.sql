-- 本地可运行的重空协同/能量优化示例数据。
-- 幂等：按项目编码、版本编码和各业务编码更新，不清空已有正式数据。
SET NAMES utf8mb4;
USE carbon_emissions;

SET @project_id := (SELECT project_id FROM energy_project WHERE project_code = 'shuohuang_demo' LIMIT 1);
SET @project_id := COALESCE(@project_id, UUID());
INSERT INTO energy_project
    (project_id, project_code, project_name, route_name, timezone, status)
VALUES
    (@project_id, 'shuohuang_demo', '朔黄演示', '朔黄线', 'Asia/Shanghai', 'active')
ON DUPLICATE KEY UPDATE
    project_name = VALUES(project_name), route_name = VALUES(route_name),
    timezone = VALUES(timezone), status = VALUES(status), updated_at = NOW();

SET @version_id := (SELECT version_id FROM energy_project_version
                    WHERE project_id = @project_id AND version_code = 'v1' LIMIT 1);
SET @version_id := COALESCE(@version_id, UUID());
INSERT INTO energy_project_version
    (version_id, project_id, version_code, version_name, data_status,
     lifecycle_status, effective_from, source_note, content_sha256, published_at)
VALUES
    (@version_id, @project_id, 'v1', '第1版', 'planning_placeholder', 'published',
     '2026-01-01 00:00:00', '朔黄重空协调规划占位示例数据，可用于页面和大屏联调。',
     SHA2('shuohuang_demo/v1/local-fixture', 256), NOW())
ON DUPLICATE KEY UPDATE
    version_name = VALUES(version_name), data_status = VALUES(data_status),
    lifecycle_status = VALUES(lifecycle_status), source_note = VALUES(source_note),
    published_at = VALUES(published_at), updated_at = NOW();

INSERT INTO energy_dept_project (dept_id, project_code, enabled, create_by, create_time)
SELECT 3000, 'shuohuang_demo', '1', 'fixture', NOW()
WHERE EXISTS (SELECT 1 FROM sys_dept WHERE dept_id = 3000)
ON DUPLICATE KEY UPDATE enabled = '1', update_by = 'fixture', update_time = NOW();

INSERT INTO energy_station
    (station_id, version_id, station_code, station_name, position_km, station_type,
     track_capacity, throat_capacity, is_terminal, source_note)
VALUES
    (UUID(), @version_id, 'SH-DZW', '定州西站', 120.500, '客货共线', 8, 4, 0, '本地联调示例'),
    (UUID(), @version_id, 'SH-SN', '肃宁北站', 286.700, '编组站', 12, 6, 0, '本地联调示例'),
    (UUID(), @version_id, 'SH-HH', '黄骅港站', 583.003, '终点站', 10, 5, 1, '本地联调示例')
ON DUPLICATE KEY UPDATE station_name = VALUES(station_name), position_km = VALUES(position_km),
    station_type = VALUES(station_type), track_capacity = VALUES(track_capacity),
    throat_capacity = VALUES(throat_capacity), is_terminal = VALUES(is_terminal),
    source_note = VALUES(source_note);

INSERT INTO energy_route_segment
    (segment_id, version_id, segment_code, start_km, end_km, gradient_permille,
     curve_radius_m, speed_limit_kmh, terrain, direction, source_note)
VALUES
    (UUID(), @version_id, 'SH-K0-K286', 0.000, 286.700, 2.100, 800.000, 120.000, '平原', 'both', '本地联调示例'),
    (UUID(), @version_id, 'SH-K286-K583', 286.700, 583.003, 1.500, 1000.000, 120.000, '沿海', 'both', '本地联调示例')
ON DUPLICATE KEY UPDATE end_km = VALUES(end_km), gradient_permille = VALUES(gradient_permille),
    speed_limit_kmh = VALUES(speed_limit_kmh), terrain = VALUES(terrain), source_note = VALUES(source_note);

INSERT INTO energy_train_type_parameter
    (train_type_id, version_id, train_type_code, train_type, mass_t, mass_min_t, mass_max_t,
     length_km, rotational_mass_factor, max_traction_kn, max_brake_kn, max_power_kw,
     davis_a, davis_b, davis_c, traction_curve_json, brake_curve_json,
     regen_power_limit_kw, regen_efficiency, direction, longitudinal_segments,
     extra_parameters_json, data_status, source_note)
VALUES
    (UUID(), @version_id, 'HH_DD', 'heavy', 10000.000, 8000.000, 12000.000, 1.200,
     1.080000, 600.000, 700.000, 9600.000, 1.50000000, 0.02000000, 0.00100000,
     JSON_ARRAY(JSON_OBJECT('speedKmh', 80, 'forceKn', 600)),
     JSON_ARRAY(JSON_OBJECT('speedKmh', 80, 'forceKn', 700)), 4800.000, 0.85000000,
     'forward', 20, JSON_OBJECT('source', 'fixture'), 'planning_placeholder', '本地联调示例')
ON DUPLICATE KEY UPDATE train_type = VALUES(train_type), mass_t = VALUES(mass_t),
    max_power_kw = VALUES(max_power_kw), source_note = VALUES(source_note);

INSERT INTO energy_storage_device
    (storage_id, version_id, storage_code, label, capacity_kwh, max_charge_power_kw,
     max_discharge_power_kw, charge_efficiency, discharge_efficiency, initial_soc_kwh,
     min_soc_kwh, max_soc_kwh, start_km, end_km, direction, available, data_status, source_note)
VALUES
    (UUID(), @version_id, 'ESS-SN-01', '肃宁北站储能示例', 12000.000, 3000.000, 3000.000,
     0.95000000, 0.95000000, 6000.000, 1200.000, 11400.000, 285.000, 288.000,
     'both', 1, 'planning_placeholder', '本地联调示例')
ON DUPLICATE KEY UPDATE label = VALUES(label), capacity_kwh = VALUES(capacity_kwh),
    max_charge_power_kw = VALUES(max_charge_power_kw), available = VALUES(available),
    source_note = VALUES(source_note);

INSERT INTO energy_power_arm
    (power_arm_id, version_id, power_arm_code, start_km, end_km, direction,
     max_traction_supply_kw, max_regen_absorption_kw, max_grid_feedback_kw,
     direct_use_allowed, needs_manual_review, data_status, source_note)
VALUES
    (UUID(), @version_id, 'PA-DZW-SN', 120.500, 286.700, 'both', 18000.000, 9000.000, 3000.000, 1, 0, 'planning_placeholder', '本地联调示例'),
    (UUID(), @version_id, 'PA-SN-HH', 286.700, 583.003, 'both', 18000.000, 9000.000, 3000.000, 1, 0, 'planning_placeholder', '本地联调示例')
ON DUPLICATE KEY UPDATE end_km = VALUES(end_km), max_traction_supply_kw = VALUES(max_traction_supply_kw), source_note = VALUES(source_note);

INSERT INTO energy_signaling_block
    (signaling_block_id, version_id, block_code, start_km, end_km, direction,
     capacity, release_margin_s, data_status, source_note)
VALUES
    (UUID(), @version_id, 'BLK-DZW-SN', 120.500, 286.700, 'both', 2, 90, 'planning_placeholder', '本地联调示例'),
    (UUID(), @version_id, 'BLK-SN-HH', 286.700, 583.003, 'both', 2, 90, 'planning_placeholder', '本地联调示例')
ON DUPLICATE KEY UPDATE end_km = VALUES(end_km), capacity = VALUES(capacity), source_note = VALUES(source_note);

INSERT INTO energy_station_resource
    (station_resource_id, version_id, station_id, track_capacity, throat_capacity,
     station_occupancy_s, throat_occupancy_s, extra_rules_json, source_note)
SELECT UUID(), @version_id, s.station_id, s.track_capacity, s.throat_capacity, 180, 90,
       JSON_OBJECT('fixture', TRUE), '本地联调示例'
FROM energy_station s
WHERE s.version_id = @version_id
  AND NOT EXISTS (SELECT 1 FROM energy_station_resource r
                  WHERE r.version_id = @version_id AND r.station_id = s.station_id);

INSERT INTO energy_timetable
    (timetable_id, version_id, timetable_code, timetable_name, service_date, data_status, source_note)
VALUES
    (UUID(), @version_id, 'TT-2026-DEMO', '朔黄联调运行图', '2026-09-29', 'planning_placeholder', '本地联调示例')
ON DUPLICATE KEY UPDATE timetable_name = VALUES(timetable_name), service_date = VALUES(service_date), source_note = VALUES(source_note);

SET @timetable_id := (SELECT timetable_id FROM energy_timetable WHERE version_id = @version_id AND timetable_code = 'TT-2026-DEMO' LIMIT 1);
SET @train_type_id := (SELECT train_type_id FROM energy_train_type_parameter WHERE version_id = @version_id AND train_type_code = 'HH_DD' LIMIT 1);
SET @origin_station_id := (SELECT station_id FROM energy_station WHERE version_id = @version_id AND station_code = 'SH-DZW' LIMIT 1);
SET @destination_station_id := (SELECT station_id FROM energy_station WHERE version_id = @version_id AND station_code = 'SH-HH' LIMIT 1);
SET @train_id := (SELECT timetable_train_id FROM energy_timetable_train WHERE timetable_id = @timetable_id AND train_no = 'SH-D001' LIMIT 1);
SET @train_id := COALESCE(@train_id, UUID());
INSERT INTO energy_timetable_train
    (timetable_train_id, timetable_id, train_type_id, train_no, direction,
     origin_station_id, destination_station_id, service_type, evaluation_enabled)
VALUES
    (@train_id, @timetable_id, @train_type_id, 'SH-D001', 'forward', @origin_station_id,
     @destination_station_id, '货运', 1)
ON DUPLICATE KEY UPDATE train_type_id = VALUES(train_type_id), direction = VALUES(direction),
    origin_station_id = VALUES(origin_station_id), destination_station_id = VALUES(destination_station_id),
    service_type = VALUES(service_type), evaluation_enabled = VALUES(evaluation_enabled);

INSERT INTO energy_timetable_stop
    (timetable_train_id, seq, station_id, arrival_time, departure_time, arrival_offset_s,
     departure_offset_s, stop_type, track, operation_type)
SELECT @train_id, 1, @origin_station_id, '2026-09-29 08:00:00', '2026-09-29 08:10:00', 0, 600, 'origin', '1', 'depart'
WHERE NOT EXISTS (SELECT 1 FROM energy_timetable_stop WHERE timetable_train_id = @train_id AND seq = 1);
INSERT INTO energy_timetable_stop
    (timetable_train_id, seq, station_id, arrival_time, departure_time, arrival_offset_s,
     departure_offset_s, stop_type, track, operation_type)
SELECT @train_id, 2, @destination_station_id, '2026-09-29 15:30:00', '2026-09-29 15:40:00', 27000, 27600, 'destination', '2', 'arrive'
WHERE NOT EXISTS (SELECT 1 FROM energy_timetable_stop WHERE timetable_train_id = @train_id AND seq = 2);

INSERT INTO energy_scenario
    (scenario_id, version_id, scenario_code, allow_direct_use, allow_storage,
     settlement_step_s, parameters_json)
VALUES
    (UUID(), @version_id, 'BASELINE', 1, 1, 60,
     JSON_OBJECT('horizonHours', 24, 'reserveSocRatio', 0.10, 'demo', TRUE))
ON DUPLICATE KEY UPDATE allow_direct_use = VALUES(allow_direct_use), allow_storage = VALUES(allow_storage),
    settlement_step_s = VALUES(settlement_step_s), parameters_json = VALUES(parameters_json);

INSERT INTO energy_dataset_file
    (version_id, relative_path, media_type, content, content_size_bytes, content_sha256)
VALUES
    (@version_id, 'fixture/stations.csv', 'text/csv', CONVERT('station_code,station_name,position_km\nSH-DZW,定州西站,120.500\nSH-SN,肃宁北站,286.700\nSH-HH,黄骅港站,583.003\n' USING utf8mb4), OCTET_LENGTH(CONVERT('station_code,station_name,position_km\nSH-DZW,定州西站,120.500\nSH-SN,肃宁北站,286.700\nSH-HH,黄骅港站,583.003\n' USING utf8mb4)), SHA2('station_code,station_name,position_km\nSH-DZW,定州西站,120.500\nSH-SN,肃宁北站,286.700\nSH-HH,黄骅港站,583.003\n', 256)),
    (@version_id, 'fixture/power_arms.csv', 'text/csv', CONVERT('power_arm_code,start_km,end_km\nPA-DZW-SN,120.500,286.700\nPA-SN-HH,286.700,583.003\n' USING utf8mb4), OCTET_LENGTH(CONVERT('power_arm_code,start_km,end_km\nPA-DZW-SN,120.500,286.700\nPA-SN-HH,286.700,583.003\n' USING utf8mb4)), SHA2('power_arm_code,start_km,end_km\nPA-DZW-SN,120.500,286.700\nPA-SN-HH,286.700,583.003\n', 256)),
    (@version_id, 'fixture/parameters.json', 'application/json', CONVERT('{"settlementStepSeconds":60,"allowStorage":true,"allowDirectUse":true}' USING utf8mb4), OCTET_LENGTH(CONVERT('{"settlementStepSeconds":60,"allowStorage":true,"allowDirectUse":true}' USING utf8mb4)), SHA2('{"settlementStepSeconds":60,"allowStorage":true,"allowDirectUse":true}', 256))
ON DUPLICATE KEY UPDATE media_type = VALUES(media_type), content = VALUES(content),
    content_size_bytes = VALUES(content_size_bytes), content_sha256 = VALUES(content_sha256);
