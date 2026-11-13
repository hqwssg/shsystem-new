package com.ruoyi.carbon.energy.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Keeps the database-backed online editor available on upgraded installations.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class EnergySchemaInitializer implements ApplicationRunner
{
    private final JdbcTemplate jdbcTemplate;

    public EnergySchemaInitializer(JdbcTemplate jdbcTemplate)
    {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(ApplicationArguments args)
    {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS energy_version_edit_sheet (
                    sheet_id bigint(20) NOT NULL AUTO_INCREMENT,
                    version_id char(36) NOT NULL,
                    topic_code varchar(64) NOT NULL,
                    sheet_name varchar(128) NOT NULL,
                    columns_json json NOT NULL,
                    rows_json json NOT NULL,
                    source_note text,
                    updated_by varchar(64),
                    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    CONSTRAINT fk_energy_edit_sheet_version FOREIGN KEY (version_id)
                        REFERENCES energy_project_version(version_id) ON DELETE CASCADE,
                    CONSTRAINT uq_energy_edit_sheet UNIQUE (version_id, topic_code, sheet_name),
                    PRIMARY KEY (sheet_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """);
    }
}
