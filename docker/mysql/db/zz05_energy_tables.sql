-- Energy recovery tables. Idempotent. Prefix energy_. Does not alter emission_* or report_*.

CREATE TABLE IF NOT EXISTS energy_project (
    project_id char(36) PRIMARY KEY,
    project_code varchar(64) NOT NULL,
    project_name varchar(200) NOT NULL,
    route_name varchar(200),
    timezone varchar(64) NOT NULL DEFAULT 'Asia/Shanghai',
    status varchar(24) NOT NULL DEFAULT 'active',
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_energy_project_code UNIQUE (project_code),
    CONSTRAINT ck_energy_project_status CHECK (status IN ('active', 'inactive', 'archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_project_version (
    version_id char(36) PRIMARY KEY,
    project_id char(36) NOT NULL,
    version_code varchar(64) NOT NULL,
    version_name varchar(200),
    data_status varchar(32) NOT NULL,
    lifecycle_status varchar(24) NOT NULL DEFAULT 'draft',
    effective_from datetime,
    effective_to datetime,
    source_note text,
    content_sha256 char(64),
    published_at datetime,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_version_project FOREIGN KEY (project_id)
        REFERENCES energy_project(project_id),
    CONSTRAINT uq_energy_version_code UNIQUE (project_id, version_code),
    CONSTRAINT ck_energy_version_data_status CHECK (
        data_status IN ('official', 'derived_from_official', 'planning_placeholder', 'synthetic')
    ),
    CONSTRAINT ck_energy_version_lifecycle CHECK (
        lifecycle_status IN ('draft', 'published', 'retired')
    ),
    CONSTRAINT ck_energy_version_effective_range CHECK (
        effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_dataset_file (
    dataset_file_id bigint(20) NOT NULL AUTO_INCREMENT,
    version_id char(36) NOT NULL,
    relative_path varchar(500) NOT NULL,
    media_type varchar(128) NOT NULL,
    content longblob NOT NULL,
    content_size_bytes bigint NOT NULL,
    content_sha256 char(64) NOT NULL,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_dataset_file_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_dataset_file_path UNIQUE (version_id, relative_path),
    CONSTRAINT ck_energy_dataset_file_path CHECK (
        relative_path <> ''
    ),
    CONSTRAINT ck_energy_dataset_file_size CHECK (content_size_bytes >= 0),
    PRIMARY KEY (dataset_file_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- Stores portable online edits when the optional external energy engine is not installed.
-- The source dataset remains unchanged; each sheet can be restored or migrated independently.
CREATE TABLE IF NOT EXISTS energy_version_edit_sheet (
    sheet_id bigint(20) NOT NULL AUTO_INCREMENT,
    version_id char(36) NOT NULL,
    topic_code varchar(64) NOT NULL,
    sheet_name varchar(128) NOT NULL,
    columns_json json NOT NULL,
    rows_json json NOT NULL,
    source_note text,
    updated_by varchar(64),
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_edit_sheet_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_edit_sheet UNIQUE (version_id, topic_code, sheet_name),
    PRIMARY KEY (sheet_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_station (
    station_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    station_code varchar(64) NOT NULL,
    station_name varchar(200) NOT NULL,
    position_km decimal(12, 3) NOT NULL,
    station_type varchar(64),
    track_capacity int,
    throat_capacity int,
    is_terminal tinyint(1) NOT NULL DEFAULT 0,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_station_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_station_version_code UNIQUE (version_id, station_code),
    CONSTRAINT uq_energy_station_version_name UNIQUE (version_id, station_name),
    CONSTRAINT ck_energy_station_position CHECK (position_km >= 0),
    CONSTRAINT ck_energy_station_capacity CHECK (
        (track_capacity IS NULL OR track_capacity >= 1)
        AND (throat_capacity IS NULL OR throat_capacity >= 1)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_route_segment (
    segment_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    segment_code varchar(64) NOT NULL,
    start_km decimal(12, 3) NOT NULL,
    end_km decimal(12, 3) NOT NULL,
    gradient_permille decimal(10, 4) NOT NULL DEFAULT 0,
    curve_radius_m decimal(14, 3),
    speed_limit_kmh decimal(10, 3),
    terrain varchar(64),
    direction varchar(16) NOT NULL DEFAULT 'both',
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_segment_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_segment_version_code UNIQUE (version_id, segment_code),
    CONSTRAINT ck_energy_segment_range CHECK (start_km >= 0 AND end_km > start_km),
    CONSTRAINT ck_energy_segment_direction CHECK (direction IN ('forward', 'reverse', 'both')),
    CONSTRAINT ck_energy_segment_curve CHECK (curve_radius_m IS NULL OR curve_radius_m > 0),
    CONSTRAINT ck_energy_segment_speed CHECK (speed_limit_kmh IS NULL OR speed_limit_kmh > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_train_type_parameter (
    train_type_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    train_type_code varchar(64) NOT NULL,
    train_type varchar(32) NOT NULL,
    mass_t decimal(14, 3) NOT NULL,
    mass_min_t decimal(14, 3),
    mass_max_t decimal(14, 3),
    length_km decimal(12, 4) NOT NULL,
    rotational_mass_factor decimal(10, 6) NOT NULL,
    max_traction_kn decimal(14, 3) NOT NULL,
    max_brake_kn decimal(14, 3) NOT NULL,
    max_power_kw decimal(16, 3) NOT NULL,
    davis_a decimal(18, 8) NOT NULL,
    davis_b decimal(18, 8) NOT NULL,
    davis_c decimal(18, 8) NOT NULL,
    traction_curve_json json,
    brake_curve_json json,
    regen_power_limit_kw decimal(16, 3),
    regen_efficiency decimal(10, 8),
    direction varchar(16) NOT NULL,
    longitudinal_segments int NOT NULL DEFAULT 1,
    extra_parameters_json json NOT NULL ,
    data_status varchar(32) NOT NULL,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_train_type_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_train_type_code UNIQUE (version_id, train_type_code),
    CONSTRAINT ck_energy_train_type_kind CHECK (train_type IN ('heavy', 'empty')),
    CONSTRAINT ck_energy_train_type_direction CHECK (direction IN ('forward', 'reverse')),
    CONSTRAINT ck_energy_train_type_positive CHECK (
        mass_t > 0 AND length_km >= 0 AND rotational_mass_factor >= 1
        AND max_traction_kn > 0 AND max_brake_kn > 0 AND max_power_kw > 0
        AND longitudinal_segments >= 1
    ),
    CONSTRAINT ck_energy_train_type_efficiency CHECK (
        regen_efficiency IS NULL OR (regen_efficiency > 0 AND regen_efficiency <= 1)
    ),
    CONSTRAINT ck_energy_train_type_data_status CHECK (
        data_status IN ('official', 'derived_from_official', 'planning_placeholder', 'synthetic')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_storage_device (
    storage_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    storage_code varchar(128) NOT NULL,
    label varchar(200),
    capacity_kwh decimal(18, 3) NOT NULL,
    max_charge_power_kw decimal(18, 3) NOT NULL,
    max_discharge_power_kw decimal(18, 3) NOT NULL,
    charge_efficiency decimal(10, 8) NOT NULL,
    discharge_efficiency decimal(10, 8) NOT NULL,
    initial_soc_kwh decimal(18, 3) NOT NULL DEFAULT 0,
    min_soc_kwh decimal(18, 3) NOT NULL DEFAULT 0,
    max_soc_kwh decimal(18, 3) NOT NULL,
    start_km decimal(12, 3) NOT NULL,
    end_km decimal(12, 3) NOT NULL,
    direction varchar(16) NOT NULL DEFAULT 'both',
    available tinyint(1) NOT NULL DEFAULT 1,
    data_status varchar(32) NOT NULL,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_storage_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_storage_code UNIQUE (version_id, storage_code),
    CONSTRAINT ck_energy_storage_range CHECK (start_km >= 0 AND end_km > start_km),
    CONSTRAINT ck_energy_storage_power CHECK (
        capacity_kwh > 0 AND max_charge_power_kw > 0 AND max_discharge_power_kw > 0
    ),
    CONSTRAINT ck_energy_storage_efficiency CHECK (
        charge_efficiency > 0 AND charge_efficiency <= 1
        AND discharge_efficiency > 0 AND discharge_efficiency <= 1
    ),
    CONSTRAINT ck_energy_storage_soc_bounds CHECK (
        min_soc_kwh >= 0 AND initial_soc_kwh >= min_soc_kwh
        AND max_soc_kwh <= capacity_kwh AND initial_soc_kwh <= max_soc_kwh
    ),
    CONSTRAINT ck_energy_storage_direction CHECK (direction IN ('forward', 'reverse', 'both')),
    CONSTRAINT ck_energy_storage_data_status CHECK (
        data_status IN ('official', 'derived_from_official', 'planning_placeholder', 'synthetic')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_power_arm (
    power_arm_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    power_arm_code varchar(128) NOT NULL,
    start_km decimal(12, 3) NOT NULL,
    end_km decimal(12, 3) NOT NULL,
    direction varchar(16) NOT NULL DEFAULT 'both',
    max_traction_supply_kw decimal(18, 3),
    max_regen_absorption_kw decimal(18, 3),
    max_grid_feedback_kw decimal(18, 3),
    direct_use_allowed tinyint(1) NOT NULL DEFAULT 0,
    needs_manual_review tinyint(1) NOT NULL DEFAULT 0,
    data_status varchar(32) NOT NULL,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_power_arm_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_power_arm_code UNIQUE (version_id, power_arm_code),
    CONSTRAINT ck_energy_power_arm_range CHECK (start_km >= 0 AND end_km > start_km),
    CONSTRAINT ck_energy_power_arm_direction CHECK (direction IN ('forward', 'reverse', 'both')),
    CONSTRAINT ck_energy_power_arm_limits CHECK (
        (max_traction_supply_kw IS NULL OR max_traction_supply_kw > 0)
        AND (max_regen_absorption_kw IS NULL OR max_regen_absorption_kw >= 0)
        AND (max_grid_feedback_kw IS NULL OR max_grid_feedback_kw >= 0)
    ),
    CONSTRAINT ck_energy_power_arm_data_status CHECK (
        data_status IN ('official', 'derived_from_official', 'planning_placeholder', 'synthetic')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_signaling_block (
    signaling_block_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    block_code varchar(128) NOT NULL,
    start_km decimal(12, 3) NOT NULL,
    end_km decimal(12, 3) NOT NULL,
    direction varchar(16) NOT NULL DEFAULT 'both',
    capacity int NOT NULL DEFAULT 1,
    release_margin_s int NOT NULL DEFAULT 0,
    data_status varchar(32) NOT NULL,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_block_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_block_code UNIQUE (version_id, block_code),
    CONSTRAINT ck_energy_block_range CHECK (start_km >= 0 AND end_km > start_km),
    CONSTRAINT ck_energy_block_direction CHECK (direction IN ('forward', 'reverse', 'both')),
    CONSTRAINT ck_energy_block_capacity CHECK (capacity >= 1 AND release_margin_s >= 0),
    CONSTRAINT ck_energy_block_data_status CHECK (
        data_status IN ('official', 'derived_from_official', 'planning_placeholder', 'synthetic')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_station_resource (
    station_resource_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    station_id char(36) NOT NULL,
    track_capacity int NOT NULL,
    throat_capacity int NOT NULL,
    station_occupancy_s int NOT NULL,
    throat_occupancy_s int NOT NULL,
    extra_rules_json json NOT NULL ,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_station_resource_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_station_resource_station FOREIGN KEY (station_id)
        REFERENCES energy_station(station_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_station_resource UNIQUE (version_id, station_id),
    CONSTRAINT ck_energy_station_resource_values CHECK (
        track_capacity >= 1 AND throat_capacity >= 1
        AND station_occupancy_s >= 0 AND throat_occupancy_s >= 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_timetable (
    timetable_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    timetable_code varchar(128) NOT NULL,
    timetable_name varchar(200),
    service_date date,
    data_status varchar(32) NOT NULL,
    source_note text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_timetable_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_timetable_code UNIQUE (version_id, timetable_code),
    CONSTRAINT ck_energy_timetable_data_status CHECK (
        data_status IN ('official', 'derived_from_official', 'planning_placeholder', 'synthetic')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_timetable_train (
    timetable_train_id char(36) PRIMARY KEY,
    timetable_id char(36) NOT NULL,
    train_type_id char(36) NOT NULL,
    train_no varchar(128) NOT NULL,
    direction varchar(16) NOT NULL,
    origin_station_id char(36),
    destination_station_id char(36),
    service_type varchar(64),
    evaluation_enabled tinyint(1) NOT NULL DEFAULT 1,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_timetable_train_timetable FOREIGN KEY (timetable_id)
        REFERENCES energy_timetable(timetable_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_timetable_train_type FOREIGN KEY (train_type_id)
        REFERENCES energy_train_type_parameter(train_type_id),
    CONSTRAINT fk_energy_timetable_train_origin FOREIGN KEY (origin_station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT fk_energy_timetable_train_destination FOREIGN KEY (destination_station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT uq_energy_timetable_train_no UNIQUE (timetable_id, train_no),
    CONSTRAINT ck_energy_timetable_train_direction CHECK (direction IN ('forward', 'reverse'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_timetable_stop (
    stop_id bigint(20) NOT NULL AUTO_INCREMENT,
    timetable_train_id char(36) NOT NULL,
    seq int NOT NULL,
    station_id char(36) NOT NULL,
    arrival_time datetime,
    departure_time datetime,
    arrival_offset_s int,
    departure_offset_s int,
    stop_type varchar(24) NOT NULL,
    track varchar(64),
    operation_type varchar(64),
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_stop_train FOREIGN KEY (timetable_train_id)
        REFERENCES energy_timetable_train(timetable_train_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_stop_station FOREIGN KEY (station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT uq_energy_stop_sequence UNIQUE (timetable_train_id, seq),
    CONSTRAINT ck_energy_stop_seq CHECK (seq >= 1),
    CONSTRAINT ck_energy_stop_offsets CHECK (
        (arrival_offset_s IS NULL OR arrival_offset_s >= 0)
        AND (departure_offset_s IS NULL OR departure_offset_s >= 0)
    ),
    CONSTRAINT ck_energy_stop_type CHECK (stop_type IN ('origin', 'pass', 'stop', 'destination')),
    PRIMARY KEY (stop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_scenario (
    scenario_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    scenario_code varchar(64) NOT NULL,
    allow_direct_use tinyint(1) NOT NULL,
    allow_storage tinyint(1) NOT NULL,
    settlement_step_s int NOT NULL,
    parameters_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_scenario_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_scenario_code UNIQUE (version_id, scenario_code),
    CONSTRAINT ck_energy_scenario_step CHECK (settlement_step_s > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_transport_task (
    task_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    task_code varchar(128) NOT NULL,
    task_type varchar(32) NOT NULL,
    origin_station_id char(36),
    destination_station_id char(36),
    required_count int NOT NULL,
    time_window_start datetime,
    time_window_end datetime,
    parameters_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_task_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_task_origin FOREIGN KEY (origin_station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT fk_energy_task_destination FOREIGN KEY (destination_station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT uq_energy_task_code UNIQUE (version_id, task_code),
    CONSTRAINT ck_energy_task_count CHECK (required_count > 0),
    CONSTRAINT ck_energy_task_window CHECK (
        time_window_end IS NULL OR time_window_start IS NULL OR time_window_end > time_window_start
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_od_demand (
    od_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    origin_station_id char(36) NOT NULL,
    destination_station_id char(36) NOT NULL,
    train_type varchar(32) NOT NULL,
    demand_count int NOT NULL,
    valid_from datetime,
    valid_to datetime,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_od_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_od_origin FOREIGN KEY (origin_station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT fk_energy_od_destination FOREIGN KEY (destination_station_id)
        REFERENCES energy_station(station_id),
    CONSTRAINT ck_energy_od_train_type CHECK (train_type IN ('heavy', 'empty')),
    CONSTRAINT ck_energy_od_count CHECK (demand_count > 0),
    CONSTRAINT ck_energy_od_window CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CONSTRAINT ck_energy_od_distinct CHECK (origin_station_id <> destination_station_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_run (
    run_id char(36) PRIMARY KEY,
    project_id char(36) NOT NULL,
    version_id char(36) NOT NULL,
    timetable_id char(36),
    scenario_id char(36),
    run_type varchar(32) NOT NULL DEFAULT 'dispatch',
    status varchar(24) NOT NULL DEFAULT 'pending',
    requested_by varchar(128),
    code_version varchar(128),
    random_seed int NOT NULL,
    input_sha256 char(64),
    result_sha256 char(64),
    error_count int NOT NULL DEFAULT 0,
    warning_count int NOT NULL DEFAULT 0,
    error_message text,
    queued_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at datetime,
    finished_at datetime,
    worker_id varchar(128),
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    idempotency_key varchar(128) NOT NULL,
    request_sha256 char(64) NOT NULL,
    attempt_count int NOT NULL DEFAULT 0,
    lease_token char(36) DEFAULT NULL,
    lease_expires_at datetime DEFAULT NULL,
    heartbeat_at datetime DEFAULT NULL,
    state_version bigint NOT NULL DEFAULT 0,
    CONSTRAINT fk_energy_run_project FOREIGN KEY (project_id)
        REFERENCES energy_project(project_id),
    CONSTRAINT fk_energy_run_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id),
    CONSTRAINT fk_energy_run_timetable FOREIGN KEY (timetable_id)
        REFERENCES energy_timetable(timetable_id),
    CONSTRAINT fk_energy_run_scenario FOREIGN KEY (scenario_id)
        REFERENCES energy_scenario(scenario_id),
    CONSTRAINT ck_energy_run_type CHECK (run_type IN ('dispatch', 'timetable_audit', 'timetable_optimization', 'rolling_rescheduling', 'joint_parameter_robustness')),
    CONSTRAINT ck_energy_run_status CHECK (
        status IN ('pending', 'validating', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT ck_energy_run_counts CHECK (error_count >= 0 AND warning_count >= 0),
    CONSTRAINT ck_energy_run_times CHECK (
        (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_run_parameter (
    run_id char(36) PRIMARY KEY,
    parameters_json json NOT NULL,
    parameter_schema_version varchar(32) NOT NULL DEFAULT '1.0',
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_run_parameter_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_run_input_snapshot (
    snapshot_id char(36) PRIMARY KEY,
    run_id char(36) NOT NULL,
    version_id char(36) NOT NULL,
    captured_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    input_sha256 char(64) NOT NULL,
    manifest_json json NOT NULL,
    frozen tinyint(1) NOT NULL DEFAULT 1,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_snapshot_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_snapshot_version FOREIGN KEY (version_id)
        REFERENCES energy_project_version(version_id),
    CONSTRAINT uq_energy_snapshot_run UNIQUE (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_run_log (
    log_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    level varchar(16) NOT NULL,
    event_code varchar(64) NOT NULL,
    message text NOT NULL,
    details_json json NOT NULL ,
    occurred_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_run_log_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT ck_energy_run_log_level CHECK (level IN ('debug', 'info', 'warning', 'error')),
    PRIMARY KEY (log_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_result_artifact (
    artifact_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    relative_path varchar(500) NOT NULL,
    artifact_type varchar(64) NOT NULL,
    media_type varchar(128) NOT NULL,
    content longblob NOT NULL,
    content_size_bytes bigint NOT NULL,
    content_sha256 char(64) NOT NULL,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_artifact_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_artifact_path UNIQUE (run_id, relative_path),
    CONSTRAINT ck_energy_artifact_path CHECK (
        relative_path <> ''
    ),
    CONSTRAINT ck_energy_artifact_size CHECK (content_size_bytes >= 0),
    PRIMARY KEY (artifact_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_optimization_candidate (
    candidate_id char(36) PRIMARY KEY,
    run_id char(36) NOT NULL,
    source_candidate_code varchar(128) NOT NULL,
    candidate_set varchar(64),
    `rank` int,
    feasible tinyint(1) NOT NULL,
    pareto tinyint(1) NOT NULL DEFAULT 0,
    energy_scenario varchar(64),
    storage_preset_id varchar(128),
    objective_priority varchar(32),
    objective_1 decimal(22, 6),
    objective_2 decimal(22, 6),
    objective_3 decimal(22, 6),
    constraint_violation decimal(22, 8) NOT NULL DEFAULT 0,
    total_cost decimal(22, 6),
    grid_kwh decimal(22, 6),
    wasted_kwh decimal(22, 6),
    recovered_energy_kwh decimal(22, 6),
    final_soc_kwh decimal(22, 6),
    resource_conflict_count int NOT NULL DEFAULT 0,
    parameters_json json NOT NULL ,
    metrics_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_candidate_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_candidate_source UNIQUE (run_id, source_candidate_code),
    CONSTRAINT ck_energy_candidate_rank CHECK (`rank` IS NULL OR `rank` >= 1),
    CONSTRAINT ck_energy_candidate_constraints CHECK (
        constraint_violation >= 0 AND resource_conflict_count >= 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_candidate_train_adjustment (
    adjustment_id bigint(20) NOT NULL AUTO_INCREMENT,
    candidate_id char(36) NOT NULL,
    train_id varchar(128) NOT NULL,
    train_type varchar(32) NOT NULL,
    sequence_no int,
    baseline_departure_s int,
    optimized_departure_s int,
    adjustment_s int NOT NULL,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_adjustment_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_adjustment_train UNIQUE (candidate_id, train_id),
    CONSTRAINT ck_energy_adjustment_train_type CHECK (train_type IN ('heavy', 'empty')),
    CONSTRAINT ck_energy_adjustment_times CHECK (
        (sequence_no IS NULL OR sequence_no >= 1)
        AND (baseline_departure_s IS NULL OR baseline_departure_s >= 0)
        AND (optimized_departure_s IS NULL OR optimized_departure_s >= 0)
    ),
    PRIMARY KEY (adjustment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_timetable_audit_summary (
    run_id char(36) PRIMARY KEY,
    valid tinyint(1) NOT NULL,
    train_count int NOT NULL DEFAULT 0,
    running_arc_count int NOT NULL DEFAULT 0,
    time_slice_count int NOT NULL DEFAULT 0,
    settlement_window_count int NOT NULL DEFAULT 0,
    energy_event_count int NOT NULL DEFAULT 0,
    issue_count int NOT NULL DEFAULT 0,
    suggestion_count int NOT NULL DEFAULT 0,
    baseline_total_gen_kwh decimal(22, 6),
    baseline_wasted_kwh decimal(22, 6),
    baseline_grid_kwh decimal(22, 6),
    summary_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_audit_summary_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT ck_energy_audit_summary_counts CHECK (
        train_count >= 0 AND running_arc_count >= 0 AND time_slice_count >= 0
        AND settlement_window_count >= 0 AND energy_event_count >= 0
        AND issue_count >= 0 AND suggestion_count >= 0
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_timetable_running_arc (
    running_arc_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    source_arc_id varchar(128),
    train_id varchar(128) NOT NULL,
    train_type varchar(32),
    direction varchar(16),
    from_station_code varchar(128),
    to_station_code varchar(128),
    arc_type varchar(64),
    start_time_s int NOT NULL,
    end_time_s int NOT NULL,
    start_km decimal(12, 3),
    end_km decimal(12, 3),
    traction_energy_kwh decimal(22, 6),
    regen_energy_kwh decimal(22, 6),
    power_arm_code varchar(128),
    storage_code varchar(128),
    details_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_running_arc_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_running_arc_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT ck_energy_running_arc_time CHECK (start_time_s >= 0 AND end_time_s >= start_time_s),
    PRIMARY KEY (running_arc_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_time_slice (
    time_slice_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    case_name varchar(64),
    slice_start_s int NOT NULL,
    slice_end_s int NOT NULL,
    power_arm_code varchar(128),
    storage_code varchar(128),
    traction_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    regen_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    accepted_by_power_arm_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    direct_used_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    battery_charge_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    battery_discharge_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    wasted_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    grid_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    soc_before_kwh decimal(22, 6),
    soc_after_kwh decimal(22, 6),
    constraint_violation_kwh decimal(22, 8) NOT NULL DEFAULT 0,
    details_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_time_slice_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_time_slice_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT ck_energy_time_slice_time CHECK (slice_start_s >= 0 AND slice_end_s > slice_start_s),
    CONSTRAINT ck_energy_time_slice_energy CHECK (
        traction_kwh >= 0 AND regen_kwh >= 0 AND accepted_by_power_arm_kwh >= 0
        AND direct_used_kwh >= 0 AND battery_charge_kwh >= 0 AND battery_discharge_kwh >= 0
        AND wasted_kwh >= 0 AND grid_kwh >= 0 AND constraint_violation_kwh >= 0
    ),
    PRIMARY KEY (time_slice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_power_arm_settlement (
    settlement_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    power_arm_code varchar(128) NOT NULL,
    window_start_s int NOT NULL,
    window_end_s int NOT NULL,
    traction_demand_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    regen_input_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    accepted_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    charge_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    discharge_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    wasted_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    grid_kwh decimal(22, 6) NOT NULL DEFAULT 0,
    max_traction_supply_kw decimal(18, 3),
    max_regen_absorption_kw decimal(18, 3),
    electrical_constraint_violation_kwh decimal(22, 8) NOT NULL DEFAULT 0,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_settlement_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_settlement_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT ck_energy_settlement_time CHECK (window_start_s >= 0 AND window_end_s > window_start_s),
    CONSTRAINT ck_energy_settlement_energy CHECK (
        traction_demand_kwh >= 0 AND regen_input_kwh >= 0 AND accepted_kwh >= 0
        AND charge_kwh >= 0 AND discharge_kwh >= 0 AND wasted_kwh >= 0 AND grid_kwh >= 0
        AND electrical_constraint_violation_kwh >= 0
    ),
    PRIMARY KEY (settlement_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_resource_conflict (
    conflict_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    case_name varchar(64),
    scenario_name varchar(64),
    conflict_type varchar(64) NOT NULL,
    severity varchar(24) NOT NULL,
    resource_code varchar(128),
    resource_name varchar(200),
    train_a varchar(128),
    train_b varchar(128),
    overlap_start_s decimal(18, 6),
    overlap_end_s decimal(18, 6),
    overlap_duration_s decimal(18, 6) NOT NULL DEFAULT 0,
    location_km decimal(12, 3),
    message text,
    suggestion text,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_conflict_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_conflict_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT ck_energy_conflict_overlap CHECK (overlap_duration_s >= 0),
    PRIMARY KEY (conflict_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_audit_issue (
    issue_id char(36) PRIMARY KEY,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    issue_type varchar(64) NOT NULL,
    severity varchar(24) NOT NULL,
    power_arm_code varchar(128),
    start_time_s int,
    end_time_s int,
    impact_kwh decimal(22, 6),
    reason text NOT NULL,
    details_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_issue_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_issue_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_optimization_suggestion (
    suggestion_id char(36) PRIMARY KEY,
    run_id char(36) NOT NULL,
    source_issue_id char(36),
    suggestion_type varchar(64) NOT NULL,
    target_train_id varchar(128),
    shift_s int,
    reason text NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'proposed',
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_suggestion_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_suggestion_issue FOREIGN KEY (source_issue_id)
        REFERENCES energy_audit_issue(issue_id) ON DELETE SET NULL,
    CONSTRAINT ck_energy_suggestion_status CHECK (status IN ('proposed', 'evaluated', 'accepted', 'rejected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_scenario_result (
    scenario_result_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    scenario_name varchar(64) NOT NULL,
    core_for_feasibility tinyint(1) NOT NULL,
    feasible tinyint(1) NOT NULL,
    blocking tinyint(1) NOT NULL,
    constraint_violation decimal(22, 8) NOT NULL DEFAULT 0,
    resource_conflict_count int NOT NULL DEFAULT 0,
    total_cost decimal(22, 6),
    grid_kwh decimal(22, 6),
    wasted_kwh decimal(22, 6),
    battery_charge_kwh decimal(22, 6),
    battery_discharge_kwh decimal(22, 6),
    final_soc_deviation_kwh decimal(22, 6),
    conflict_summary text,
    details_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_scenario_result_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_scenario_result_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_scenario_result UNIQUE (run_id, candidate_id, scenario_name),
    CONSTRAINT ck_energy_scenario_result_values CHECK (
        constraint_violation >= 0 AND resource_conflict_count >= 0
    ),
    PRIMARY KEY (scenario_result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_result_kpi (
    result_kpi_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    candidate_id char(36),
    case_name varchar(64) NOT NULL,
    feasible tinyint(1) NOT NULL,
    total_gen_kwh decimal(22, 6),
    total_con_kwh decimal(22, 6),
    accepted_by_power_arm_kwh decimal(22, 6),
    recovered_energy_kwh decimal(22, 6),
    recovery_rate decimal(16, 10),
    direct_used_kwh decimal(22, 6),
    battery_charge_kwh decimal(22, 6),
    battery_discharge_kwh decimal(22, 6),
    wasted_kwh decimal(22, 6),
    grid_kwh decimal(22, 6),
    effective_regen_loss_kwh decimal(22, 6),
    final_soc_kwh decimal(22, 6),
    constraint_violation decimal(22, 8) NOT NULL DEFAULT 0,
    resource_conflict_count int NOT NULL DEFAULT 0,
    total_cost decimal(22, 6),
    metrics_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_kpi_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_kpi_candidate FOREIGN KEY (candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_kpi_case UNIQUE (run_id, candidate_id, case_name),
    CONSTRAINT ck_energy_kpi_values CHECK (
        constraint_violation >= 0 AND resource_conflict_count >= 0
        AND (recovery_rate IS NULL OR recovery_rate >= 0)
    ),
    PRIMARY KEY (result_kpi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_optimization_decision (
    run_id char(36) PRIMARY KEY,
    action varchar(32) NOT NULL,
    selected_candidate_id char(36),
    reason varchar(128) NOT NULL,
    baseline_effective_regen_loss_kwh decimal(22, 6),
    baseline_grid_kwh decimal(22, 6),
    effective_regen_loss_improvement_kwh decimal(22, 6),
    grid_improvement_kwh decimal(22, 6),
    decision_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_decision_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT fk_energy_decision_candidate FOREIGN KEY (selected_candidate_id)
        REFERENCES energy_optimization_candidate(candidate_id) ON DELETE SET NULL,
    CONSTRAINT ck_energy_decision_action CHECK (action IN ('optimize', 'keep_baseline', 'no_feasible_solution'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_rolling_control_event (
    event_id char(36) PRIMARY KEY,
    run_id char(36) NOT NULL,
    cycle_index int NOT NULL,
    current_time_s int NOT NULL,
    commit_status varchar(48) NOT NULL,
    safety_state varchar(48) NOT NULL,
    safety_action varchar(96) NOT NULL,
    core_robust_feasible tinyint(1) NOT NULL,
    operational_intervention_required tinyint(1) NOT NULL,
    attempt_count int NOT NULL,
    request_fingerprint char(64) NOT NULL,
    event_json json NOT NULL ,
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_rolling_event_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_rolling_event_cycle UNIQUE (run_id, cycle_index),
    CONSTRAINT ck_energy_rolling_event_nonnegative CHECK (
        cycle_index >= 0 AND current_time_s >= 0 AND attempt_count >= 1
    ),
    CONSTRAINT ck_energy_rolling_event_commit CHECK (
        commit_status IN (
            'committed_robust_feasible',
            'withheld_infeasible',
            'committed_infeasible_experiment_only'
        )
    ),
    CONSTRAINT ck_energy_rolling_event_state CHECK (
        safety_state IN (
            'normal',
            'recovered_automatically',
            'recovered_after_observation',
            'waiting_for_observation',
            'manual_intervention_required',
            'experiment_only'
        )
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_run_state_event (
    event_id bigint(20) NOT NULL AUTO_INCREMENT,
    run_id char(36) NOT NULL,
    state_version bigint NOT NULL,
    from_status varchar(24),
    to_status varchar(24) NOT NULL,
    worker_id varchar(128),
    lease_token char(36),
    reason varchar(128) NOT NULL,
    details_json json NOT NULL ,
    occurred_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_energy_run_event_run FOREIGN KEY (run_id)
        REFERENCES energy_run(run_id) ON DELETE CASCADE,
    CONSTRAINT uq_energy_run_event_version UNIQUE (run_id, state_version),
    CONSTRAINT ck_energy_run_event_version CHECK (state_version >= 0),
    CONSTRAINT ck_energy_run_event_from_status CHECK (
        from_status IS NULL OR from_status IN (
            'pending', 'validating', 'running', 'succeeded', 'failed', 'cancelled'
        )
    ),
    CONSTRAINT ck_energy_run_event_to_status CHECK (
        to_status IN (
            'pending', 'validating', 'running', 'succeeded', 'failed', 'cancelled'
        )
    ),
    PRIMARY KEY (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS energy_dept_project (
  id                bigint(20)   NOT NULL AUTO_INCREMENT,
  dept_id           bigint(20)   NOT NULL,
  project_code      varchar(64)  NOT NULL,
  enabled           char(1)      NOT NULL DEFAULT '0',
  create_by         varchar(64)  DEFAULT '',
  create_time       datetime     DEFAULT NULL,
  update_by         varchar(64)  DEFAULT '',
  update_time       datetime     DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_energy_dept_project (dept_id, project_code),
  KEY idx_energy_dept_project_code (project_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录部门与能量项目对照';

CREATE INDEX idx_energy_dataset_file_version
    ON energy_dataset_file(version_id);

CREATE INDEX idx_energy_station_version_position
    ON energy_station(version_id, position_km);

CREATE INDEX idx_energy_segment_version_range
    ON energy_route_segment(version_id, start_km, end_km);

CREATE INDEX idx_energy_power_arm_version_range
    ON energy_power_arm(version_id, start_km, end_km);

CREATE INDEX idx_energy_run_status_queue
    ON energy_run(status, queued_at);

CREATE INDEX idx_energy_run_project_created
    ON energy_run(project_id, created_at);

CREATE INDEX idx_energy_run_log_run_time
    ON energy_run_log(run_id, occurred_at);

CREATE INDEX idx_energy_artifact_run
    ON energy_result_artifact(run_id);

CREATE INDEX idx_energy_candidate_run_rank
    ON energy_optimization_candidate(run_id, `rank`);

CREATE INDEX idx_energy_energy_slice_run_time
    ON energy_time_slice(run_id, case_name, slice_start_s);

CREATE INDEX idx_energy_running_arc_run_train
    ON energy_timetable_running_arc(run_id, train_id, start_time_s);

CREATE INDEX idx_energy_conflict_run_type
    ON energy_resource_conflict(run_id, conflict_type, overlap_start_s);

CREATE INDEX idx_energy_scenario_run
    ON energy_scenario_result(run_id, scenario_name);

CREATE INDEX idx_energy_kpi_run
    ON energy_result_kpi(run_id, case_name);

CREATE INDEX idx_energy_rolling_event_run_time
    ON energy_rolling_control_event(run_id, current_time_s);

CREATE UNIQUE INDEX uq_energy_run_idempotency ON energy_run(project_id, idempotency_key);

CREATE INDEX idx_energy_run_expired_lease ON energy_run(status, lease_expires_at);

CREATE INDEX idx_energy_run_event_timeline ON energy_run_state_event(run_id, state_version);
