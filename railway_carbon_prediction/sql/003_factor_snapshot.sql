-- 003_factor_snapshot.sql
-- 为已有库补充因子版本、供热面积系数和排放结果快照字段。
-- 本脚本使用动态 DDL，可重复执行；不会删除或覆盖历史值。
USE `carbon_emissions`;

-- 1) prediction_emission_factor.factor_version
SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_emission_factor` ADD COLUMN `factor_version` VARCHAR(64) NOT NULL DEFAULT ''legacy'' COMMENT ''因子版本，如 EF-ELEC-2025'' AFTER `factor_unit`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_emission_factor'
    AND column_name = 'factor_version'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) prediction_caliber_rule.rule_version
SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_caliber_rule` ADD COLUMN `rule_version` VARCHAR(64) NOT NULL DEFAULT ''legacy'' COMMENT ''规则版本，如 CAL-2025'' AFTER `unit`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_caliber_rule'
    AND column_name = 'rule_version'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3) prediction_emission_monthly snapshot columns
SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_emission_monthly` ADD COLUMN `factor_version` VARCHAR(128) DEFAULT NULL COMMENT ''本次使用的因子版本组合'' AFTER `heat_factor`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_emission_monthly'
    AND column_name = 'factor_version'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_emission_monthly` ADD COLUMN `heat_area_factor` DECIMAL(18,8) DEFAULT NULL COMMENT ''本次使用的供热面积系数'' AFTER `factor_version`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_emission_monthly'
    AND column_name = 'heat_area_factor'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_emission_monthly` ADD COLUMN `factor_source` VARCHAR(255) DEFAULT NULL COMMENT ''因子来源摘要'' AFTER `heat_area_factor`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_emission_monthly'
    AND column_name = 'factor_source'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_emission_monthly` ADD COLUMN `factor_snapshot` JSON DEFAULT NULL COMMENT ''本次使用的完整因子快照'' AFTER `factor_source`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_emission_monthly'
    AND column_name = 'factor_snapshot'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4) 历史版本回填（只填空值）
UPDATE `prediction_emission_factor`
SET `factor_version` = CONCAT('EF-', REPLACE(`var_id`, '_TOTAL', ''), '-', YEAR(`effective_from`))
WHERE `factor_version` IS NULL OR `factor_version` = 'legacy';

UPDATE `prediction_caliber_rule`
SET `rule_version` = CONCAT('CAL-', `org_id`, '-', YEAR(`effective_from`))
WHERE `rule_version` IS NULL OR `rule_version` = 'legacy';

-- 5) 历史排放结果回填版本与供热面积系数
UPDATE `prediction_emission_monthly` e
JOIN `prediction_emission_factor` f
  ON f.`var_id` = 'ELEC_TOTAL'
 AND e.`period` >= f.`effective_from`
 AND (f.`effective_to` IS NULL OR e.`period` <= f.`effective_to`)
JOIN `prediction_caliber_rule` r
  ON r.`rule_type` = 'heat_area_factor'
 AND r.`org_id` = e.`org_id`
 AND e.`period` >= r.`effective_from`
 AND (r.`effective_to` IS NULL OR e.`period` <= r.`effective_to`)
SET e.`factor_version` = CONCAT(f.`factor_version`, '|', r.`rule_version`),
    e.`heat_area_factor` = r.`rule_value`,
    e.`factor_source` = f.`factor_source`
WHERE e.`factor_version` IS NULL;

-- 6) 版本索引（可重复执行）
SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_emission_factor` ADD KEY `idx_var_version` (`var_id`,`factor_version`)',
    'DO 0')
  FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'prediction_emission_factor'
    AND index_name = 'idx_var_version'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
