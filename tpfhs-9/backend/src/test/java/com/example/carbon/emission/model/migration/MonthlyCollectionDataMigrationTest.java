package com.example.carbon.emission.model.migration;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class MonthlyCollectionDataMigrationTest {

    @Test
    void createsOnlyTheRequestedLatestMonthlyTableAndIsIdempotent() throws IOException {
        String sql = resource("schema-update-20261028-collection-point-monthly-data.sql");

        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS emission_collection_node_data_month")
                .contains("UNIQUE (collection_point_type, collection_point_id, year, month)")
                .contains("information_schema.statistics")
                .contains("CREATE INDEX idx_month_year_month")
                .contains("CREATE INDEX idx_month_data_status")
                .contains("energy_attribution_dept_id")
                .contains("energy_attribution_station_id")
                .doesNotContain("calculation_node_id")
                .doesNotContain("template_id")
                .doesNotContain("dqi_")
                .doesNotContain("INSERT INTO")
                .doesNotContain("UPDATE emission_collection_node_data_month");
    }

    private String resource(String name) throws IOException {
        try (var input = getClass().getClassLoader().getResourceAsStream(name)) {
            if (input == null) throw new IOException("missing resource " + name);
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
