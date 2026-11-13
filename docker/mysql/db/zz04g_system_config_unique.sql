-- Repair historical duplicate system parameters and prevent them from recurring.
-- The highest config_id is retained because it is the most recently inserted copy.
DELETE duplicate_config
FROM sys_config duplicate_config
JOIN sys_config retained_config
  ON retained_config.config_key = duplicate_config.config_key
 AND retained_config.config_id > duplicate_config.config_id;

SET @sys_config_unique_exists := (
    SELECT COUNT(*)
    FROM (
        SELECT index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'sys_config'
        GROUP BY index_name
        HAVING MAX(non_unique) = 0
           AND COUNT(*) = 1
           AND MAX(CASE WHEN column_name = 'config_key' THEN 1 ELSE 0 END) = 1
    ) existing_unique_config_indexes
);
SET @sys_config_unique_sql := IF(
    @sys_config_unique_exists = 0,
    'ALTER TABLE sys_config ADD UNIQUE INDEX uk_sys_config_config_key (config_key)',
    'SELECT 1'
);
PREPARE sys_config_unique_stmt FROM @sys_config_unique_sql;
EXECUTE sys_config_unique_stmt;
DEALLOCATE PREPARE sys_config_unique_stmt;
