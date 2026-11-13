# Official Intake Templates

Fill these templates when official data arrives, or provide native official files plus a mapping note.

| Template | Purpose | Target runtime file |
| --- | --- | --- |
| `../running_diagram_template.xlsx` | Official timetable converted into internal canonical form | timetable audit/optimizer inputs |
| `vehicle_dynamics_intake.xlsx` | Traction/brake/Davis parameters | `data/real_shuohuang/trains.csv` |
| `power_arm_electrical_intake.xlsx` | Power-arm electrical limits | `data/real_shuohuang/power_arm_intervals.csv` |
| `storage_intake.xlsx` | Storage equipment and section bounds | `data/real_shuohuang/battery.json` + storage flags |
| `signaling_blocks_intake.xlsx` | Signaling/block capacity | `signaling_blocks.csv` |
| `initial_inventory_intake.xlsx` | Initial heavy/empty stock | `resource_config.json` |

See `docs/official_data_intake_checklist.md` for field requirements and validation commands.
