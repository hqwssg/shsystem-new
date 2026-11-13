-- 复制模板的节点需要保留源节点关系，供报告按部门主体节点筛选。
-- 可重复执行，适用于已存在的 carbon_emissions 数据库。
SET NAMES utf8mb4;
USE `carbon_emissions`;

SET @db := DATABASE();
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.columns
       WHERE table_schema = @db AND table_name = 'emission_node'
         AND column_name = 'source_node_id') = 0,
    'ALTER TABLE emission_node ADD COLUMN source_node_id BIGINT DEFAULT 0 COMMENT ''源节点ID'' AFTER template_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.statistics
       WHERE table_schema = @db AND table_name = 'emission_node'
         AND index_name = 'idx_emission_node_source') = 0,
    'ALTER TABLE emission_node ADD INDEX idx_emission_node_source (source_node_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
