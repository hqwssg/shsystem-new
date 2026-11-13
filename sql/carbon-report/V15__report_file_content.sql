-- 报告配图、Word、PDF 的正式内容放在 report_file.content。object_key 只留给尚未迁入的旧文件。
-- default_slot 只在 kind = 'default' 时有值，用来保证每个部门每种默认图只有一行。

SET NAMES utf8mb4;
USE carbon_emissions;

SET @col := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND COLUMN_NAME = 'content');
SET @ddl := IF(@col = 0, 'ALTER TABLE report_file ADD COLUMN content LONGBLOB NULL COMMENT ''文件内容'' AFTER object_key', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @nullable := (SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND COLUMN_NAME = 'object_key');
SET @ddl := IF(@nullable = 'NO', 'ALTER TABLE report_file MODIFY COLUMN object_key varchar(512) NULL DEFAULT ''''', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @slot := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND COLUMN_NAME = 'default_slot');
SET @ddl := IF(@slot = 0, 'ALTER TABLE report_file ADD COLUMN default_slot varchar(128) GENERATED ALWAYS AS (CASE WHEN kind = ''default'' THEN CONCAT(dept_id, ''/'', role) ELSE NULL END) STORED', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND INDEX_NAME = 'uq_report_file_default_slot');
SET @ddl := IF(@idx = 0, 'ALTER TABLE report_file ADD UNIQUE KEY uq_report_file_default_slot (default_slot)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
