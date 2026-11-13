package com.example.carbon.emission.model.migration;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

class TrendPredictionAutoIngestConfigMigrationTest {

    private static final String CONFIG_KEY =
            "carbon.trend-prediction.auto-ingest-company-monthly-data";

    @Test
    void migrationDefinesProtectedDisabledBooleanConfigWithoutOverwritingExistingValue() throws Exception {
        String sql = Files.readString(Path.of(
                "src/main/resources/schema-update-20261103-trend-prediction-auto-ingest.sql"));

        assertConfigContract(sql);
        assertThat(sql)
                .contains("WHERE NOT EXISTS")
                .contains("WHERE config_key = '" + CONFIG_KEY + "'")
                .doesNotContain("UPDATE sys_config")
                .doesNotContain("DELETE FROM sys_config")
                .doesNotContain("config_id");
    }

    @Test
    void newDatabaseSchemaCarriesTheSameConfigContract() throws Exception {
        String sql = Files.readString(Path.of("src/main/resources/schema.sql"));

        assertConfigContract(sql);
    }

    private void assertConfigContract(String sql) {
        assertThat(sql)
                .contains("'碳排放趋势预测-自动使用分公司月度能耗统计'")
                .contains("'" + CONFIG_KEY + "'")
                .contains("'false', 'Y', 'admin', CURRENT_TIMESTAMP")
                .contains("true：开启；false：关闭")
                .contains("WHERE NOT EXISTS");
    }
}
