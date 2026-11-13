# 模块功能说明：验证数据库集成约定可解析且不会混入其他模块表前缀。

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "database" / "database_contract.json"
CONVENTIONS_PATH = ROOT / "docs" / "database_integration_phase1_conventions.md"
SCHEMA_DOC_PATH = ROOT / "docs" / "simulation_program_database_schema.md"


def main() -> int:
    """检查第一阶段冻结项和数据字典中的物理表命名。"""

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    database = contract["database"]
    assert database["engine"] == "postgresql"
    assert database["minimum_major_version"] >= 16
    assert database["name"] == "carbon_emissions"
    assert database["schema"] == "energy_recovery"
    assert database["table_prefix"] == "simulation_"
    assert contract["connection"]["dsn_environment_variable"] == "SIMULATION_DATABASE_URL"
    assert contract["connection"]["credentials_in_repository"] is False

    conventions = CONVENTIONS_PATH.read_text(encoding="utf-8")
    schema_doc = SCHEMA_DOC_PATH.read_text(encoding="utf-8")
    for required in (
        "`carbon_emissions`",
        "`energy_recovery`",
        "`simulation_`",
        "`SIMULATION_DATABASE_URL`",
    ):
        assert required in conventions
    assert "`era_`" not in conventions
    assert "`era_`" not in schema_doc

    physical_tables = []
    for line in schema_doc.splitlines():
        if not line.startswith("### "):
            continue
        for token in line.split("`")[1::2]:
            if token.startswith("simulation_"):
                physical_tables.append(token)
    assert physical_tables
    assert all(name.startswith("simulation_") for name in physical_tables)
    assert len(physical_tables) == len(set(physical_tables))

    print("database integration phase-1 contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
