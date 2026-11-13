-- MySQL 8.0.16+. Run before deploying the sixth-task code; no business data is inserted.
ALTER TABLE energy_run
    DROP CHECK ck_energy_run_type;

ALTER TABLE energy_run
    ADD CONSTRAINT ck_energy_run_type CHECK (
        run_type IN (
            'dispatch', 'timetable_audit', 'timetable_optimization',
            'rolling_rescheduling', 'joint_parameter_robustness', 'storage_planning'
        )
    );

CREATE TABLE IF NOT EXISTS energy_storage_candidate_site (
    candidate_site_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    site_code varchar(128) NOT NULL,
    site_name varchar(200) NOT NULL,
    position_km decimal(12,3) NOT NULL,
    power_arm_code varchar(128) NOT NULL,
    storage_section_start_km decimal(12,3) NOT NULL,
    storage_section_end_km decimal(12,3) NOT NULL,
    direction varchar(16) NOT NULL,
    buildable boolean NOT NULL,
    max_connection_power_kw decimal(18,3) NOT NULL,
    max_capacity_kwh decimal(18,3) NOT NULL,
    fixed_site_cost_cny decimal(22,2) NOT NULL,
    allowed_technology_codes_json json NOT NULL,
    data_status varchar(32) NOT NULL,
    source_note text,
    UNIQUE (version_id, site_code),
    CHECK (storage_section_end_km > storage_section_start_km),
    CHECK (position_km BETWEEN storage_section_start_km AND storage_section_end_km),
    CHECK (direction IN ('forward','reverse','both')),
    CHECK (data_status IN ('official','derived_from_official','planning_placeholder','synthetic')),
    FOREIGN KEY (version_id) REFERENCES energy_project_version(version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_technology (
    storage_technology_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    technology_code varchar(128) NOT NULL,
    technology_name varchar(200) NOT NULL,
    parameters_json json NOT NULL,
    data_status varchar(32) NOT NULL,
    source_note text,
    UNIQUE (version_id, technology_code),
    CHECK (JSON_TYPE(parameters_json) = 'OBJECT'),
    CHECK (data_status IN ('official','derived_from_official','planning_placeholder','synthetic')),
    FOREIGN KEY (version_id) REFERENCES energy_project_version(version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_site_technology_option (
    option_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    site_code varchar(128) NOT NULL,
    technology_code varchar(128) NOT NULL,
    limits_json json NOT NULL,
    available boolean NOT NULL,
    source_note text,
    UNIQUE (version_id, site_code, technology_code),
    CHECK (JSON_TYPE(limits_json) = 'OBJECT'),
    FOREIGN KEY (version_id) REFERENCES energy_project_version(version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_planning_scenario (
    planning_scenario_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    scenario_set_code varchar(128) NOT NULL,
    scenario_code varchar(128) NOT NULL,
    scenario_name varchar(200) NOT NULL,
    weight decimal(14,10) NOT NULL,
    core_for_feasibility boolean NOT NULL,
    scenario_json json NOT NULL,
    data_status varchar(32) NOT NULL,
    source_note text,
    UNIQUE (version_id, scenario_set_code, scenario_code),
    CHECK (weight > 0),
    CHECK (JSON_TYPE(scenario_json) = 'OBJECT'),
    FOREIGN KEY (version_id) REFERENCES energy_project_version(version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_planning_policy (
    planning_policy_id char(36) PRIMARY KEY,
    version_id char(36) NOT NULL,
    policy_code varchar(128) NOT NULL,
    policy_json json NOT NULL,
    data_status varchar(32) NOT NULL,
    source_note text,
    UNIQUE (version_id, policy_code),
    CHECK (JSON_TYPE(policy_json) = 'OBJECT'),
    FOREIGN KEY (version_id) REFERENCES energy_project_version(version_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_plan (
    storage_plan_id char(36) PRIMARY KEY,
    run_id char(36) NOT NULL,
    source_plan_code varchar(128) NOT NULL,
    `rank` integer,
    selected boolean NOT NULL DEFAULT false,
    feasible boolean NOT NULL,
    within_budget boolean NOT NULL,
    meets_business_thresholds boolean NOT NULL,
    site_count integer NOT NULL,
    site_codes text,
    total_capacity_kwh decimal(22,6) NOT NULL,
    total_charge_power_kw decimal(22,6) NOT NULL,
    total_discharge_power_kw decimal(22,6) NOT NULL,
    capex_cny decimal(24,2) NOT NULL,
    annual_total_cost_cny decimal(24,2) NOT NULL,
    annual_saving_vs_no_build_cny decimal(24,2),
    grid_reduction_vs_no_build_kwh_per_year decimal(24,6),
    rejection_reasons text,
    metrics_json json NOT NULL,
    UNIQUE (run_id, source_plan_code),
    FOREIGN KEY (run_id) REFERENCES energy_run(run_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_plan_device (
    storage_plan_device_id bigint AUTO_INCREMENT PRIMARY KEY,
    storage_plan_id char(36) NOT NULL,
    device_index integer NOT NULL,
    site_code varchar(128) NOT NULL,
    technology_code varchar(128) NOT NULL,
    capacity_kwh decimal(22,6) NOT NULL,
    charge_power_kw decimal(22,6) NOT NULL,
    discharge_power_kw decimal(22,6) NOT NULL,
    capex_cny decimal(24,2) NOT NULL,
    device_json json NOT NULL,
    UNIQUE (storage_plan_id, device_index),
    FOREIGN KEY (storage_plan_id) REFERENCES energy_storage_plan(storage_plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_plan_scenario_result (
    storage_plan_scenario_result_id bigint AUTO_INCREMENT PRIMARY KEY,
    storage_plan_id char(36) NOT NULL,
    scenario_code varchar(128) NOT NULL,
    core_for_feasibility boolean NOT NULL,
    feasible boolean NOT NULL,
    grid_kwh decimal(22,6),
    wasted_kwh decimal(22,6),
    storage_charge_kwh decimal(22,6),
    storage_discharge_kwh decimal(22,6),
    final_soc_kwh decimal(22,6),
    annual_operating_cost_cny decimal(24,2),
    result_json json NOT NULL,
    UNIQUE (storage_plan_id, scenario_code),
    FOREIGN KEY (storage_plan_id) REFERENCES energy_storage_plan(storage_plan_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS energy_storage_plan_decision (
    run_id char(36) PRIMARY KEY,
    decision varchar(32) NOT NULL,
    selected_storage_plan_id char(36),
    best_build_storage_plan_id char(36),
    decision_reason varchar(256) NOT NULL,
    recommendation_level varchar(64) NOT NULL,
    formal_engineering_conclusion_allowed boolean NOT NULL,
    complete_for_declared_domain boolean NOT NULL,
    decision_json json NOT NULL,
    FOREIGN KEY (run_id) REFERENCES energy_run(run_id) ON DELETE CASCADE,
    FOREIGN KEY (selected_storage_plan_id) REFERENCES energy_storage_plan(storage_plan_id) ON DELETE SET NULL,
    FOREIGN KEY (best_build_storage_plan_id) REFERENCES energy_storage_plan(storage_plan_id) ON DELETE SET NULL,
    CHECK (decision IN ('recommend_build','keep_no_build','no_feasible_plan'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_simulation_storage_plan_run_rank
    ON energy_storage_plan(run_id, `rank`);
CREATE INDEX idx_simulation_storage_plan_scenario_plan
    ON energy_storage_plan_scenario_result(storage_plan_id, scenario_code);
