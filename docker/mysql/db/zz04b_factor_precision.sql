-- Compatibility update for databases created before factor precision was fixed.
-- Older deployments may not have created this optional table yet. In that case,
-- Hibernate/schema.sql will create it later with the correct DECIMAL(18,6) type.
SET @factor_value_column_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'emission_default_factor'
      AND COLUMN_NAME = 'factor_value'
);
SET @factor_precision_ddl := IF(
    @factor_value_column_exists > 0,
    'ALTER TABLE emission_default_factor MODIFY COLUMN factor_value DECIMAL(18,6) DEFAULT NULL',
    'SELECT 1'
);
PREPARE factor_precision_stmt FROM @factor_precision_ddl;
EXECUTE factor_precision_stmt;
DEALLOCATE PREPARE factor_precision_stmt;
