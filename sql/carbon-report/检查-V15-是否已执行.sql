-- 只读检查：report_file 是否具备 V15 内容列与 default_slot 约束
-- 在目标库（如 carbon_emissions）执行

SET NAMES utf8mb4;

SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND COLUMN_NAME = 'content') AS has_content_column,
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND COLUMN_NAME = 'default_slot') AS has_default_slot,
  (SELECT COUNT(*) FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_file' AND INDEX_NAME = 'uq_report_file_default_slot') AS has_default_slot_unique;

-- 期望：三列均为 1。任一为 0 则执行 shsystem-main/sql/carbon-report/V15__report_file_content.sql
