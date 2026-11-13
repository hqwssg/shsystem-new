# Project Structure

> 当前文档层级、发布版本和有效结论统一以 `docs/current_documentation_baseline.md` 为准；本文件只描述目录和入口。

This file describes the current project structure and recommended entry points.

The active scope is Shuohuang mainline heavy-empty train dispatch, timetable energy audit, regenerative-braking energy settlement, and candidate optimization plans.

## Unified Entry

| File | Role |
| --- | --- |
| `run_project.py` | Recommended project entry. Wraps data build, validation, meter samples, timetable audit, timetable optimization, dispatch simulation, and smoke checks. |
| `README.md` | Usage guide and current trust boundary. |
| `docs/INDEX.md` | Documentation index for current functions, experiments, and reference material. |
| `docs/current_documentation_baseline.md` | Unique current-status authority and document precedence rules. |
| `docs/document_status_registry.json` | Machine-readable classification of every maintained document. |
| `docs/current_project_status_and_io.md` | Current status, input lifecycle, output contract, KPI definitions, and known limits. |
| `docs/database_integration_phase1_conventions.md` | Frozen database name, `simulation_` table prefix, naming, time, security, and transaction conventions. |
| `database/database_contract.json` | Machine-readable database integration contract used by later schema and adapter work. |
| `database/interface_contract_freeze.json` | Frozen platform/database logical interface version, public enums, compatibility policy, and file hashes. |
| `database/platform_api_contract.json` | Machine-readable platform operations, run state machine, and result query contract. |
| `database/migrations/` | Executable PostgreSQL schema migrations for all `simulation_` tables. |
| `database/cli.py` | Database bootstrap, migration, import, run, worker, status, and export entry. |
| `docs/database_integration_guide.md` | Deployment and platform integration guide for the completed database path. |
| `release/release_baseline.json` | Formal software baseline with the exact release file set, sizes, and SHA-256 values. |
| `docs/release_baseline_and_delivery.md` | Complete algorithm package scope, build, verification, and unified release gate. |
| `docs/long_test_performance_gate.md` | Long-running regression timing, process-tree memory, and performance gate contract. |
| `operations/` | Non-secret production assurance policy and worker process templates. |
| `docs/production_assurance_toolkit_guide.md` | Production assurance toolkit entry points, local drill, and handoff boundary. |

Prefer `run_project.py` for daily work. Lower-level scripts are retained for focused debugging and reproduction.

## Stable Commands

| Command | Status | Output |
| --- | --- | --- |
| `python run_project.py simulate` | Recommended end-to-end simulation workflow | `outputs/SIMULATION_TEST_REPORT.md` |
| `python run_project.py validate-data` | Runs; smart-meter station overlap is a warning/degraded item | `outputs/data_quality_validation/` |
| `python run_project.py meter-samples` | Runs representative smart-meter sampling and route alignment | `data/real_shuohuang/`, `outputs/energy_calibration_alignment/` |
| `python run_project.py audit-timetable` | Runs on the preset timetable template | `outputs/timetable_energy_audit/` |
| `python run_project.py optimize-timetable` | Runs NSGA-II timetable optimization | `outputs/timetable_optimizer_nsga2/` |
| `python run_project.py dispatch-case` | Runs storage-only heavy-empty dispatch simulation; overridden phases receive a phase-specific suffix unless `--output-dir` is explicit | `outputs/dispatch_storage_no_direct_phase2600/` by default |
| `python run_project.py experiment-suite` | Runs multi-case simulation and sensitivity tests | `outputs/simulation_experiment_suite/` |
| `python run_project.py check-ingestion` | Checks new official data before replacing current inputs | `outputs/real_data_ingestion_check/` |
| `python run_project.py smoke` | Runs current smoke checks | Terminal output |
| `python tools/run_release_acceptance.py` | Runs the complete formal release gate, including all long regressions | `outputs/release_acceptance/` |
| `python run_project.py benchmark-small-optimality-gap` | Exhaustively evaluates a declared 2/4/6-train discrete domain and compares three NSGA-II budgets | `paper/experiments/E12_small_scale_optimality_gap/` |

Every unified-entry invocation also writes a schema-`1.1` run manifest under `outputs/run_manifests/` (or the selected output root). The manifest captures the raw command, serialized arguments and stable argument hash, explicit random seeds, code/input/output SHA-256 snapshots, platform and dependency versions, data status, validation summary, return code, and duration.

## Main Algorithm Modules

| File | Purpose |
| --- | --- |
| `run_dispatch_case.py` | Current storage-only heavy-empty dispatch experiment and report generation. |
| `heavy_empty_network_optimizer.py` | Heavy-empty double-layer time-space network optimization prototype. |
| `time_space_network.py` | Time-space node and arc structures. |
| `rolling_optimizer.py` | Candidate generation, rolling optimization helpers, and objective logic. |
| `scheduler_nsga2.py` | Multi-objective optimization components. |
| `resource_constraints.py` | Resource checks for intervals, stations, throats, and technical-operation times. |
| `exact_resource_feasibility.py` | Exact mixed-integer resource-feasibility solver used to verify heuristic results and distinguish search misses from proven infeasibility. |
| `energy_settlement.py` | Energy settlement for direct use, storage, grid energy, wasted energy, and power-arm capacity limits. |
| `power_arm_lookup.py` | Power-arm interval lookup by kilometer marker. |
| `power_arm_electrical_limits.py` | Power-arm electrical limit defaults, isolated up/down rule, and storage-section logic. |
| `train_simulator.py` | Train movement and energy-estimation helpers. |

## Timetable Modules

| File | Purpose |
| --- | --- |
| `timetable_input.py` | Timetable template loading, field validation, and formation mass mapping. |
| `timetable_energy_audit.py` | Timetable energy-waste detection, power-arm splitting, and time-slice settlement. |
| `timetable_optimizer.py` | Rule-based candidates and NSGA-II timetable optimization prototype. |

## Smart-Meter Modules

| File | Current status |
| --- | --- |
| `smart_meter_adapter.py` | Loads and maps smart-meter source fields. The SS4 `status` field is not used for valid-record filtering. |
| `smart_meter_time_matcher.py` | Supports strict overlap rejection and overlap exclusion. |
| `smart_meter_representative_sampler.py` | Current practical path for validation coverage; excludes overlapped station intervals. |
| `energy_calibration_alignment.py` | Aligns representative or legacy calibration samples with route arcs. |
| `run_energy_calibration_pipeline.py` | Still available for focused calibration experiments; default project simulation uses representative samples. |

## Data and Templates

| Path | Purpose |
| --- | --- |
| `data/real_shuohuang/` | Default real-data dataset used by current algorithms. |
| `data_templates/` | Timetable and heavy-empty dispatch input templates. |
| `database/` | Database integration contracts and, in later phases, versioned schema migrations. |
| `outputs/run_manifests/` | Automatically generated per-run reproducibility and audit records. |
| `鏈旈粍鏁版嵁/` | Reviewed source data and provider documents. |
| `tools/build_real_shuohuang_dataset.py` | Builds `data/real_shuohuang/` from `data/source/` reviewed English-named source tables. |
| `tools/setup_utf8_env.ps1` | Configures the current PowerShell session for UTF-8 console and Python IO. |
| `tools/performance_analysis.py` | Runs isolated cProfile benchmarks and writes reproducible timing/hotspot reports. |
| `tools/sync_prototype_html.py` | Regenerates the standalone prototype wrapper from the editable fragment. |
| `tools/synthetic_scenario_matrix.py` | Runs the deterministic synthetic edge-case coverage matrix. |
| `tools/synthetic_regression_baseline.py` | Creates and checks strict output-fingerprint baselines for the synthetic matrix. |
| `tools/official_data_readiness_pipeline.py` | Read-only official-data acceptance, isolated simulation, output audit, and KPI comparison. |
| `tools/performance_capacity_analysis.py` | Runs repeatable multi-scale timing checks and capacity reports. |
| `tools/run_exact_resource_feasibility.py` | Reproduces exact resource-feasibility checks and writes auditable JSON evidence. |
| `tools/verify_f16_exact_end_to_end.py` | Verifies that an exact F16 seed entered full dispatch evaluation and passed every current core gate. |
| `tools/verify_f16_exact_quality_end_to_end.py` | Verifies the F16 lexicographic adjustment optimum and compares its full evaluation with the original exact seed. |
| `tools/validate_prototype_contract.py` | Checks prototype UI fields against the machine-readable backend contract. |
| `tools/run_ci_checks.py` | Runs the local CI-style quality gate and writes check summaries. |
| `tools/freeze_release_baseline.py` | Explicitly freezes the selected software payload for a new release. |
| `tools/build_algorithm_delivery_package.py` | Builds the complete baseline-bound algorithm directory and ZIP package. |
| `tools/verify_algorithm_delivery_package.py` | Rejects source or package file drift, tampering, missing files, and extra files. |
| `tools/verify_release_package_runtime.py` | Extracts the ZIP in isolation, verifies exact dependencies, and runs representative package-local smoke checks. |
| `tools/run_release_acceptance.py` | Unifies baseline, package, contract, CI, short-smoke, and long-regression gates. |
| `tools/compile_project.py` | Compiles project-owned Python files while excluding incompatible environments and generated data. |
| `data_quality_validator.py` | Project-level data-quality validator. |
| `real_data_ingestion_checker.py` | File-level pre-ingestion gate for newly delivered official data. |

## Tests

| Path | Purpose |
| --- | --- |
| `tests/smoke/` | Current smoke checks. |
| `tests/legacy/` | Historical checks retained for traceability, not current main entry points. |

## Historical or Auxiliary Scripts

These files are retained for historical experiments or focused analysis, but are not recommended daily entry points:

| File | Purpose |
| --- | --- |
| `sandbox_data.py`, `sandbox_config.json` | Early virtual-data generation and configuration. |
| `run_virtual_algorithm_outputs.py` | Early virtual-data output generation. |
| `run_ablation_experiments.py` | Ablation experiments. |
| `run_extended_experiments.py` | Extended experiments. |
| `run_engineering_solver_experiments.py` | Engineering solver experiments. |

## Maintenance Rules

1. Use `run_project.py simulate` as the main end-to-end simulation entry.
2. Current algorithms read `data/real_shuohuang/` by default and should not silently fall back to virtual data.
3. Smart-meter station overlaps should be excluded from representative validation samples instead of blocking the whole project.
4. Placeholder or preset data must remain clearly marked until official values are available.
5. When new provider data arrives, update the data validator and README first, then refresh the simulation workflow.
6. Keep only current results and delivery/review materials at the first level of `outputs/`; move probes, smoke outputs, and superseded scenarios under `outputs/archive/`.
7. Before any archive/delete operation, run `python tools/project_hygiene.py report` and review `outputs/project_hygiene_report/PROJECT_HYGIENE_REPORT.md`; the tool is read-only.
8. Keep `outputs/run_manifests/` as current audit evidence; do not classify it as an old scenario or delete it during routine output cleanup.
