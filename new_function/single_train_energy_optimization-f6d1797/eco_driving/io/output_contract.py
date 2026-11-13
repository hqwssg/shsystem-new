"""面向 heavy-empty 的 eco-driving 正式输出契约。"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class EcoDrivingOutputRecord:
    train_id: str
    train_type: str
    route_start_km: float
    route_end_km: float
    scenario: str
    target_runtime_s: Optional[float]
    baseline_runtime_s: float
    optimized_runtime_s: float
    baseline_section_energy_kwh: float
    optimized_section_energy_kwh: float
    baseline_traction_energy_kwh: float
    optimized_traction_energy_kwh: float
    baseline_braking_energy_kwh: float
    optimized_braking_energy_kwh: float
    baseline_regenerative_energy_kwh: float
    optimized_regenerative_energy_kwh: float
    baseline_soc_end: float
    optimized_soc_end: float
    energy_saving_kwh: Optional[float]
    energy_saving_percent: Optional[float]
    runtime_constraint_feasible: bool
    optimized_constraint_violations: str
    controller_name: str
    data_status: str
    disclaimer: str = "仿真结果，不作为工程结论"
    comparison_feasible: bool = True

    def as_dict(self) -> Mapping[str, Any]:
        return asdict(self)


def write_output_records(records: list[EcoDrivingOutputRecord], out_dir: Path, manifest: Mapping[str, Any]) -> Mapping[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [record.as_dict() for record in records]
    csv_path = out_dir / "eco_driving_results.csv"
    json_path = out_dir / "eco_driving_results.json"
    manifest_path = out_dir / "package_manifest.json"
    fields = list(rows[0]) if rows else list(EcoDrivingOutputRecord.__dataclass_fields__)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"csv": csv_path, "json": json_path, "manifest": manifest_path}
