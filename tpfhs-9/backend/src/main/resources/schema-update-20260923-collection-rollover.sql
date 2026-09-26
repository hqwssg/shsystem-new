SET NAMES utf8mb4;
USE `carbon_emissions`;

DELIMITER $$
DROP PROCEDURE IF EXISTS add_column_if_missing$$
CREATE PROCEDURE add_column_if_missing(IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition VARCHAR(1000))
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = DATABASE() AND table_name = p_table AND column_name = p_column) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
        PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL add_column_if_missing('emission_meter_info','rollover_enabled','TINYINT DEFAULT 0 COMMENT ''累计表是否允许按归零阈值修正'' AFTER `is_cumulative`');
CALL add_column_if_missing('emission_meter_info','rollover_threshold','DECIMAL(18,6) NULL COMMENT ''归零阈值/计数周期'' AFTER `rollover_enabled`');
CALL add_column_if_missing('emission_fossil_fuel_meter_info','rollover_enabled','TINYINT DEFAULT 0 COMMENT ''累计表是否允许按归零阈值修正'' AFTER `is_cumulative`');
CALL add_column_if_missing('emission_fossil_fuel_meter_info','rollover_threshold','DECIMAL(18,6) NULL COMMENT ''归零阈值/计数周期'' AFTER `rollover_enabled`');
CALL add_column_if_missing('emission_purchased_heat_meter_info','rollover_enabled','TINYINT DEFAULT 0 COMMENT ''累计表是否允许按归零阈值修正'' AFTER `is_cumulative`');
CALL add_column_if_missing('emission_purchased_heat_meter_info','rollover_threshold','DECIMAL(18,6) NULL COMMENT ''归零阈值/计数周期'' AFTER `rollover_enabled`');
CALL add_column_if_missing('emission_collection_record','external_record_id','VARCHAR(128) NULL COMMENT ''外部数据源记录ID'' AFTER `reading_value`');
CALL add_column_if_missing('emission_collection_record','external_quality','VARCHAR(30) NULL COMMENT ''外部数据质量标识'' AFTER `external_record_id`');
CALL add_column_if_missing('emission_collection_record','collection_failure_reason','VARCHAR(500) NULL COMMENT ''采集失败的脱敏原因'' AFTER `external_quality`');
CALL add_column_if_missing('emission_collection_node_data','rollover_applied','BOOLEAN DEFAULT FALSE COMMENT ''本次活动量是否使用归零修正'' AFTER `adjusted_energy_value`');
CALL add_column_if_missing('emission_collection_node_data','rollover_threshold','DECIMAL(18,6) NULL COMMENT ''本次核算采用的归零阈值快照'' AFTER `rollover_applied`');

DROP PROCEDURE IF EXISTS add_column_if_missing;

SELECT table_name, column_name FROM information_schema.columns
WHERE table_schema = DATABASE() AND column_name IN
('rollover_enabled','rollover_threshold','external_record_id','external_quality','collection_failure_reason','rollover_applied')
ORDER BY table_name, ordinal_position;
