-- Read-only platform query examples. Bind :run_id in the database client.

-- 1. Task status and immutable input/result identities.
SELECT run_id, run_type, status, queued_at, started_at, finished_at,
       error_count, warning_count, error_message, input_sha256, result_sha256,
       attempt_count, state_version
FROM energy_recovery.simulation_run
WHERE run_id = :'run_id'::uuid;

-- 2. Append-only lifecycle events.
SELECT state_version, from_status, to_status, reason, occurred_at, details_json
FROM energy_recovery.simulation_run_state_event
WHERE run_id = :'run_id'::uuid
ORDER BY state_version;

-- 3. Overview decision and KPI cards.
SELECT action, reason, selected_candidate_id, decision_json
FROM energy_recovery.simulation_optimization_decision
WHERE run_id = :'run_id'::uuid;

SELECT case_name, feasible, recovered_energy_kwh, recovery_rate,
       grid_kwh, wasted_kwh, battery_charge_kwh, battery_discharge_kwh,
       final_soc_kwh, constraint_violation, resource_conflict_count, total_cost
FROM energy_recovery.simulation_result_kpi
WHERE run_id = :'run_id'::uuid
ORDER BY case_name;

-- 4. Candidate and scenario detail.
SELECT source_candidate_code, rank, feasible, pareto, energy_scenario,
       storage_preset_id, objective_1, objective_2, objective_3,
       constraint_violation, resource_conflict_count
FROM energy_recovery.simulation_optimization_candidate
WHERE run_id = :'run_id'::uuid
ORDER BY rank NULLS LAST, source_candidate_code;

SELECT scenario_name, core_for_feasibility, feasible, blocking,
       constraint_violation, resource_conflict_count, total_cost,
       grid_kwh, wasted_kwh, final_soc_deviation_kwh
FROM energy_recovery.simulation_scenario_result
WHERE run_id = :'run_id'::uuid
ORDER BY scenario_result_id;

-- 5. Energy timeline and rolling-control timeline.
SELECT case_name, slice_start_s, slice_end_s, power_arm_code, storage_code,
       traction_kwh, regen_kwh, accepted_by_power_arm_kwh, direct_used_kwh,
       battery_charge_kwh, battery_discharge_kwh, wasted_kwh, grid_kwh,
       soc_before_kwh, soc_after_kwh, constraint_violation_kwh
FROM energy_recovery.simulation_energy_time_slice
WHERE run_id = :'run_id'::uuid
ORDER BY case_name, slice_start_s;

SELECT cycle_index, current_time_s, commit_status, safety_state, safety_action,
       core_robust_feasible, operational_intervention_required, attempt_count,
       event_json
FROM energy_recovery.simulation_rolling_control_event
WHERE run_id = :'run_id'::uuid
ORDER BY cycle_index;

-- 6. Artifact catalogue. Fetch content only in an authenticated download endpoint.
SELECT relative_path, media_type, content_size_bytes, content_sha256, created_at
FROM energy_recovery.simulation_result_artifact
WHERE run_id = :'run_id'::uuid
ORDER BY relative_path;

-- 7. Operations dashboard.
SELECT status, count(*) AS task_count,
       min(queued_at) AS oldest_queued_at,
       max(heartbeat_at) AS latest_heartbeat_at
FROM energy_recovery.simulation_run
GROUP BY status
ORDER BY status;
