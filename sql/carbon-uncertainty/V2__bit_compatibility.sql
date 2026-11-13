-- Normalize legacy BIT(1) flags to the TINYINT(1) types declared by the
-- uncertainty schema. Values remain 0/1; this only repairs JDBC metadata so
-- Hibernate schema validation can start on databases created by older scripts.
SET NAMES utf8mb4;

SET @enabled_type := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'uncertainty_dimension_rule'
      AND COLUMN_NAME = 'enabled'
      AND DATA_TYPE = 'bit'
);
SET @sql := IF(
    @enabled_type > 0,
    'ALTER TABLE uncertainty_dimension_rule MODIFY enabled TINYINT(1) NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Shared calculation entities also contain Boolean flags.  Older databases
-- may have created them as BIT(1), while the uncertainty service validates
-- them as MySQL TINYINT(1).  Normalize only when the metadata is still BIT;
-- values remain 0/1 and existing business rows are preserved.
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emission_calculation_node' AND COLUMN_NAME = 'include_in_calculation' AND DATA_TYPE = 'bit') > 0,
    'ALTER TABLE emission_calculation_node MODIFY include_in_calculation TINYINT(1) NOT NULL DEFAULT 1',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'emission_collection_node_data' AND COLUMN_NAME = 'rollover_applied' AND DATA_TYPE = 'bit') > 0,
    'ALTER TABLE emission_collection_node_data MODIFY rollover_applied TINYINT(1) NULL DEFAULT 0',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uncertainty_run' AND COLUMN_NAME = 'point_cov_in_ci' AND DATA_TYPE = 'bit') > 0,
    'ALTER TABLE uncertainty_run MODIFY point_cov_in_ci TINYINT(1) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uncertainty_run' AND COLUMN_NAME = 'raw_le_cov' AND DATA_TYPE = 'bit') > 0,
    'ALTER TABLE uncertainty_run MODIFY raw_le_cov TINYINT(1) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @default_filled_type := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'uncertainty_dimension_rule'
      AND COLUMN_NAME = 'mark_default_filled'
      AND DATA_TYPE = 'bit'
);
SET @sql := IF(
    @default_filled_type > 0,
    'ALTER TABLE uncertainty_dimension_rule MODIFY mark_default_filled TINYINT(1) NOT NULL DEFAULT 0',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
