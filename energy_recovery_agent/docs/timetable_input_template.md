# Timetable Evaluation Input Template

## Purpose

`data_templates/running_diagram_template.xlsx` is the current internal canonical timetable template. It is not an official railway timetable format. When the official format is available, add an adapter that converts the official fields into this canonical structure, then reuse the same validation, energy audit, and optimization modules.

## Workflow

1. The user fills in train metadata, station-by-station arrival/departure times, energy scenarios, and constraints.
2. `timetable_input.py` validates the template and converts it into canonical timetable records.
3. `timetable_energy_audit.py` builds running arcs, splits them by power-arm boundaries, expands them into time slices, and performs power-arm energy settlement.
4. The audit outputs waste defects and optimization suggestions. If no defect is found, the report marks the timetable as reasonable for the tested scenario assumptions.

## Sheets

### `trains`

Train-level metadata.

| Field | Meaning | Use |
| --- | --- | --- |
| `train_id` | Unique train identifier | Links timetable rows, nodes, arcs, and energy rows |
| `train_type` | Train class, for example `Heavy` or `Empty` | Selects prototype energy parameters |
| `direction` | `forward` or `reverse` | Validates mileage order |
| `origin_station` | Origin station | Route boundary check |
| `destination_station` | Destination station | Route boundary check |
| `mass_t` | Train mass in tonnes | Prototype energy scaling |
| `formation` | Formation description | Audit note |
| `traction_type` | Traction type | Future traction-model selection |
| `priority` | Priority | Future optimization ranking |
| `formation_category` | Optional 2025 formation category, e.g. `two_10000_ton`, `unit_10000_ton`, `combined_10000_ton`, `ordinary` | Looks up `data/real_shuohuang/train_formation_modes_2025.csv` |
| `load_state` | Optional `heavy` or `empty` | Narrows formation lookup |
| `formation_mode` | Optional formation mode, e.g. `1+1`, `2+0`, `单牵` | Narrows formation lookup |
| `wagon_count` | Optional wagon count | Narrows formation lookup |
| `mass_source` | Output/trace note | Documents whether mass came from input or the formation catalog |

If `mass_t` is filled, it is kept as the explicit user value. If `mass_t` is blank and the optional formation fields identify exactly one row in `data/real_shuohuang/train_formation_modes_2025.csv`, the loader fills `mass_t` from that catalog. If both are present but disagree, the loader keeps `mass_t` and reports a warning.

### `timetable`

Station-by-station timetable rows.

| Field | Meaning | Use |
| --- | --- | --- |
| `train_id` | Train identifier | Links to `trains.train_id` |
| `seq` | Stop sequence within one train | Route order |
| `station_name` | Station or point name | Human-readable audit label |
| `station_km` | Mileage in km | Arc start/end position |
| `arrival_time` | Arrival time | Node time |
| `departure_time` | Departure time | Waiting or operation arc end time |
| `stop_type` | `origin`, `pass`, `stop`, or `destination` | Node and audit context |
| `track` | Track or line | Future station resource constraint |
| `operation_type` | `waiting`, `loading`, `unloading`, `dismantling`, etc. | Station activity arc type |
| `note` | Free-form note | Audit trace |

Times should use `HH:MM:SS` or seconds. `station_km` uses km.

### `scenario`

Energy-use assumptions.

| Scenario | Direct use | Storage | Meaning |
| --- | --- | --- | --- |
| `storage_no_direct` | FALSE | TRUE | Direct use is not allowed; storage is available only in configured storage sections |

Current Shuohuang rule: up/down power supply is isolated, so `direct_used_kwh` should remain zero. Because regenerated energy cannot be used without storage, `storage_no_direct` is the only current main scenario. Storage parameters and storage-section boundaries are planning assumptions unless installed equipment data is provided.

### `constraints`

Expandable timetable constraints such as headway, power-arm matching scope, technical operation times, station capacity, or track rules.

### `metadata`

Route name, template version, purpose, and time zone.

## Current Audit Outputs

`timetable_energy_audit.py` writes:

- `validation_issues.csv`
- `timetable_nodes_draft.csv`
- `timetable_arcs_draft.csv`
- `timetable_running_arcs.csv`
- `timetable_energy_time_slices.csv`
- `timetable_power_arm_settlement.csv`
- `audit_issues.csv`
- `optimization_suggestions.csv`
- `scenario_summary.csv`
- `TIMETABLE_ENERGY_AUDIT_REPORT.md`

## Current Limits

- Regenerative energy is still estimated from the prototype gradient/curve energy adjustment, not from a full traction-braking simulation.
- The continuous power-arm interval table is still an inferred draft and needs manual confirmation.
- Official timetable format support should be implemented as a separate adapter, not by changing the audit core.
- `1+1`, `2+0`, and `单牵` are currently treated as formation labels only. Their locomotive configuration meaning still needs railway-side confirmation.
