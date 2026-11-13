package com.example.carbon.emission.model.migration;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class NodeFactorSnapshotMigrationTest {

    @Test
    void clearsOnlyIncompleteLegacySnapshotsWithoutHardCodedNodeIds() throws IOException {
        String sql = resource("schema-update-20261019-node-factor-snapshot.sql");

        assertThat(sql).contains("SET NAMES utf8mb4")
                .contains("carbon_emission_factor IS NULL")
                .contains("carbon_emission_factor IS NOT NULL")
                .contains("NULLIF(TRIM(carbon_emission_factor_unit), '')")
                .contains("carbon_emission_factor_description = NULL")
                .doesNotContain("2280")
                .doesNotContain("2284")
                .doesNotContain("DELETE FROM");
    }

    @Test
    void addsProvenanceAndDqiSnapshotColumnsWithoutGuessingLegacyReferences() throws IOException {
        String sql = resource("schema-update-20261026-node-factor-provenance.sql");

        assertThat(sql).contains("SET NAMES utf8mb4")
                .contains("information_schema.columns")
                .contains("carbon_emission_factor_source")
                .contains("carbon_emission_factor_id")
                .contains("carbon_emission_factor_name")
                .contains("carbon_emission_factor_data_year")
                .contains("carbon_emission_factor_dqi_e1_score")
                .contains("carbon_emission_factor_dqi_e6_score")
                .contains("SELECT node_id")
                .doesNotContain("UPDATE emission_node_config")
                .doesNotContain("DELETE FROM emission_node_config");
    }

    private String resource(String name) throws IOException {
        try (var input = getClass().getClassLoader().getResourceAsStream(name)) {
            if (input == null) throw new IOException("missing resource " + name);
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
