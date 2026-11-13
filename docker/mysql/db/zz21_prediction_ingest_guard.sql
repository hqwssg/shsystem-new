-- 005_ingest_guard_audit.sql
-- 月度入库锁、payload_hash、覆盖审计。可重复执行。
USE `carbon_emissions`;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_ingest_batch` ADD COLUMN `payload_hash` VARCHAR(64) DEFAULT NULL COMMENT ''请求体规范化 SHA-256'' AFTER `idempotency_key`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_ingest_batch'
    AND column_name = 'payload_hash'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_ingest_batch` ADD COLUMN `override_flag` TINYINT(1) NOT NULL DEFAULT 0 AFTER `payload_hash`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_ingest_batch'
    AND column_name = 'override_flag'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_ingest_batch` ADD COLUMN `override_reason` VARCHAR(512) DEFAULT NULL AFTER `override_flag`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_ingest_batch'
    AND column_name = 'override_reason'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_ingest_batch` ADD COLUMN `replaces_batch_id` VARCHAR(40) DEFAULT NULL AFTER `override_reason`',
    'DO 0')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'prediction_ingest_batch'
    AND column_name = 'replaces_batch_id'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE `prediction_ingest_batch` ADD KEY `idx_period` (`period_start`,`period_end`)',
    'DO 0')
  FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'prediction_ingest_batch'
    AND index_name = 'idx_period'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS `prediction_ingest_audit` (
  `id`                BIGINT       NOT NULL AUTO_INCREMENT,
  `batch_id`          VARCHAR(40)  NOT NULL,
  `replaces_batch_id` VARCHAR(40)  DEFAULT NULL,
  `org_id`            VARCHAR(16)  NOT NULL,
  `period`            DATE         NOT NULL,
  `entity_type`       VARCHAR(16)  NOT NULL,
  `entity_key`        VARCHAR(96)  NOT NULL,
  `var_id`            VARCHAR(32)  DEFAULT NULL,
  `old_value`         DECIMAL(20,6) DEFAULT NULL,
  `new_value`         DECIMAL(20,6) DEFAULT NULL,
  `old_status`        VARCHAR(32)  DEFAULT NULL,
  `new_status`        VARCHAR(32)  DEFAULT NULL,
  `detail`            JSON         DEFAULT NULL,
  `operator`          VARCHAR(64)  DEFAULT NULL,
  `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_batch` (`batch_id`),
  KEY `idx_org_period` (`org_id`,`period`),
  KEY `idx_entity` (`entity_type`,`entity_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='入库覆盖审计（活动/排放/异常旧值）';
