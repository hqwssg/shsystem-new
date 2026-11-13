package com.example.carbon.emission.model.migration;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class MonthlyNodeCompanyDataMigrationTest {

    @Test
    void migrationDefinesStableKeysStatusesAndIdempotentGuards() throws Exception {
        String sql = Files.readString(Path.of("src/main/resources/schema-update-20261103-node-company-monthly-data.sql"));

        assertThat(sql).contains("CREATE TABLE IF NOT EXISTS emission_calc_node_summary_month")
                .contains("UNIQUE (template_id, source_node_id, year, month, emission_subcategory)")
                .contains("missing_collection_point_ids VARCHAR(500)")
                .contains("result_status TINYINT NOT NULL DEFAULT 1")
                .contains("CREATE TABLE IF NOT EXISTS emission_company_energy_summary_month")
                .contains("uk_company_month_energy_subcategory UNIQUE")
                .contains("(company_dept_id, year, month, energy_category_l1, emission_subcategory)")
                .contains("ingest_status TINYINT NOT NULL DEFAULT 0")
                .contains("information_schema.statistics")
                .doesNotContain("INSERT INTO emission_calc_node_summary_month")
                .doesNotContain("INSERT INTO emission_company_energy_summary_month")
                .doesNotContain("UPDATE emission_calc_node_summary_month")
                .doesNotContain("UPDATE emission_company_energy_summary_month");
    }
}
