-- Add complete factor-dimension audit fields and align electricity activity
-- units. This migration upgrades the existing carbon_emissions schema; it
-- does not create a new database and does not recalculate historical results.
-- New nullable columns intentionally leave historical rows unchanged.

SET NAMES utf8mb4;
USE `carbon_emissions`;

DELIMITER $$
DROP PROCEDURE IF EXISTS add_column_if_missing$$
CREATE PROCEDURE add_column_if_missing(
    IN p_table_name VARCHAR(64),
    IN p_column_name VARCHAR(64),
    IN p_definition VARCHAR(500)
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = p_table_name
          AND column_name = p_column_name
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table_name, '` ADD COLUMN `',
                          p_column_name, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL add_column_if_missing(
    'emission_node_config',
    'carbon_emission_factor_unit',
    'VARCHAR(100) NULL COMMENT ''碳排放因子单位（值和单位成对保存）'' AFTER `carbon_emission_factor`'
);
CALL add_column_if_missing(
    'emission_collection_node_data',
    'carbon_emission_factor_unit',
    'VARCHAR(100) NULL COMMENT ''本次核算实际采用的因子单位快照'' AFTER `carbon_emission_factor`'
);
CALL add_column_if_missing(
    'emission_collection_node_data',
    'carbon_emission_unit',
    'VARCHAR(30) NULL COMMENT ''碳排放结果统一单位，新核算固定为tCO2e'' AFTER `carbon_emission_factor_unit`'
);

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- 扩充碳排放结果精度；只改变列定义，不重算或改写历史数值。
ALTER TABLE emission_collection_node_data
    MODIFY COLUMN carbon_emission DECIMAL(18,9) NULL COMMENT '折算的碳排放量（统一为tCO2e）',
    MODIFY COLUMN adjusted_carbon_emission DECIMAL(18,9) NULL COMMENT '经过计算修正后的碳排放量（统一为tCO2e）';
ALTER TABLE emission_calc_node_summary
    MODIFY COLUMN direct_carbon_emission DECIMAL(18,9) DEFAULT 0 COMMENT '本节点直接碳排放（tCO2e）',
    MODIFY COLUMN subtotal_carbon_emission DECIMAL(18,9) DEFAULT 0 COMMENT '本节点子树合计碳排放（tCO2e）',
    MODIFY COLUMN carbon_emission_factor DECIMAL(18,9) NULL COMMENT '本节点该组等效碳因子（tCO2e/核算单位）';

-- 旧版本中 status 允许 NULL 且无默认值；量纲解析只接受显式启用记录。
-- 统一表定义，但不改变已有的显式停用状态。
ALTER TABLE emission_factor_unit
    MODIFY COLUMN status TINYINT DEFAULT 1 COMMENT '状态：1-启用，0-停用';

START TRANSACTION;

UPDATE emission_calc_unit_default
SET calculation_unit = 'MWh',
    report_unit = 'MWh',
    remark = '电力活动量统一换算为MWh后汇总'
WHERE subcategory_code IN ('PE_PF', 'PE_AS')
  AND (calculation_unit <> 'MWh'
       OR report_unit <> 'MWh'
       OR remark <> '电力活动量统一换算为MWh后汇总');

INSERT INTO emission_calc_unit_default
    (subcategory_code, subcategory_name, calculation_unit, report_unit, remark)
VALUES
    ('PE_SS', '电网输送损失', 'MWh', 'MWh', '电力活动量统一换算为MWh后汇总')
ON DUPLICATE KEY UPDATE
    subcategory_name = VALUES(subcategory_name),
    calculation_unit = VALUES(calculation_unit),
    report_unit = VALUES(report_unit),
    remark = VALUES(remark);

INSERT IGNORE INTO emission_unit_conversion
    (subcategory_code, from_unit_code, to_unit_code, conversion_factor, remark)
VALUES
    ('PE_SS', 'kWh', 'MWh', 0.001, '1 MWh = 1000 kWh'),
    ('PE_SS', 'MWh', 'kWh', 1000, '反向');

INSERT IGNORE INTO emission_factor_unit
    (factor_unit_code, factor_unit_name, numerator_ghg_code,
     denominator_unit_code, subcategory_code, sort_order, status)
VALUES
    ('tCO2_per_kWh', 'tCO₂/kWh', 'tCO2', 'kWh', 'PE_PF', 3, 1),
    ('tCO2_per_kWh_AS', 'tCO₂/kWh', 'tCO2', 'kWh', 'PE_AS', 3, 1),
    ('tCO2_per_kWh_SS', 'tCO₂/kWh', 'tCO2', 'kWh', 'PE_SS', 3, 1);

UPDATE emission_factor_unit
SET status = 1
WHERE factor_unit_code IN ('tCO2_per_kWh', 'tCO2_per_kWh_AS', 'tCO2_per_kWh_SS')
  AND status IS NULL;

COMMIT;

-- Idempotency evidence: all three values must be 1 and PE_* units must be MWh.
SELECT COUNT(*) AS node_factor_unit_column_count
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'emission_node_config'
  AND column_name = 'carbon_emission_factor_unit';

SELECT COUNT(*) AS result_dimension_column_count
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name = 'emission_collection_node_data'
  AND column_name IN ('carbon_emission_factor_unit', 'carbon_emission_unit');

SELECT subcategory_code, calculation_unit, report_unit
FROM emission_calc_unit_default
WHERE subcategory_code IN ('PE_PF', 'PE_AS', 'PE_SS')
ORDER BY subcategory_code;
