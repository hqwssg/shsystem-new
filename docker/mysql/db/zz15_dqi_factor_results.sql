-- ============================================================
-- 更新脚本 2026-10-21
-- 变更：
--   1) 四张排放因子表新增 EF 评分维度字段，每表 12 列：
--      emission_electricity_carbon_emission_factor（电力）
--      emission_fossil_fuel_emission_factor（化石燃料）
--      emission_thermal_emission_factor（热力）
--      emission_waste_incineration_factor（固废焚烧）
--        驱动字段：ef_source_authority(E1来源权威性)
--                 ef_completeness_scope(E2组分完整性)
--                 ef_data_region(E3地理适用性)
--                 ef_data_year(E4因子数据年份，按与核算年度差 Δt 评分)
--                 ef_tech_applicability(E5技术工况适用性)
--                 ef_conversion_chain(E6单位换算链可靠性)
--        维度得分：dqi_e1_score ~ dqi_e6_score
--      用途：因子级评分信息相对固定，核算时由不确定性分析模块（DQI+MCS）
--            沿用表内记录自动评分，无需逐次人工打分。
--   2) emission_collection_node_data（各采集节点本次核算结果表）新增评分
--      结果字段 10 列：
--        AD 评分：dqi_a1_score / dqi_a2_score / dqi_a4_score / dqi_a6_score
--        EF 评分：dqi_e1_score ~ dqi_e6_score
--      用途：生成结果记录时，把对应采集点的 AD 评分、本次采用的排放因子
--            的 EF 评分写入结果行；后续不确定性分析直接从本表读取评分记录。
--            （A5 时间同步性按数据年份差动态计算，不属于采集点固定属性，
--             与上一轮采集点表口径一致，不纳入。）
-- 初始化：存量 emission_collection_node_data 记录评分统一设为 3 分（测试用）；
--       因子表驱动字段/得分保持 NULL，由因子维护时按实际来源填写。
-- 幂等：逐列判断是否已存在，可重复执行；UPDATE 对全部行生效。
-- ============================================================

SET SQL_SAFE_UPDATES = 0;

-- ------------------------------------------------------------
-- 1) emission_electricity_carbon_emission_factor（电力碳排放因子库表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'ef_source_authority');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN ef_source_authority VARCHAR(40) COMMENT ''DQI-E1驱动 来源权威性：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated'' AFTER description', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'ef_completeness_scope');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN ef_completeness_scope VARCHAR(40) COMMENT ''DQI-E2驱动 组分完整性：full/minor_missing/partial_missing/major_only/unknown'' AFTER ef_source_authority', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'ef_data_region');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN ef_data_region VARCHAR(40) COMMENT ''DQI-E3驱动 地理适用性：in_boundary/same_grid/national/similar_economy/other_country'' AFTER ef_completeness_scope', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'ef_data_year');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN ef_data_year INT COMMENT ''DQI-E4驱动 因子数据年份：与核算年度差 Δt 决定时间适用性得分'' AFTER ef_data_region', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'ef_tech_applicability');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN ef_tech_applicability VARCHAR(40) COMMENT ''DQI-E5驱动 技术工况适用性：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default'' AFTER ef_data_year', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'ef_conversion_chain');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN ef_conversion_chain VARCHAR(40) COMMENT ''DQI-E6驱动 单位换算链可靠性：direct_match/standard_single/multi_step/derived_from_other/unclear'' AFTER ef_tech_applicability', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'dqi_e1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN dqi_e1_score TINYINT COMMENT ''DQI-E1 来源权威性得分（1-5）'' AFTER ef_conversion_chain', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'dqi_e2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN dqi_e2_score TINYINT COMMENT ''DQI-E2 组分完整性得分（1-5）'' AFTER dqi_e1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'dqi_e3_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN dqi_e3_score TINYINT COMMENT ''DQI-E3 地理适用性得分（1-5）'' AFTER dqi_e2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'dqi_e4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN dqi_e4_score TINYINT COMMENT ''DQI-E4 时间适用性得分（1-5）'' AFTER dqi_e3_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'dqi_e5_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN dqi_e5_score TINYINT COMMENT ''DQI-E5 技术工况适用性得分（1-5）'' AFTER dqi_e4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_electricity_carbon_emission_factor' AND column_name = 'dqi_e6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_electricity_carbon_emission_factor ADD COLUMN dqi_e6_score TINYINT COMMENT ''DQI-E6 单位换算链可靠性得分（1-5）'' AFTER dqi_e5_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2) emission_fossil_fuel_emission_factor（化石燃料排放因子库表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'ef_source_authority');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN ef_source_authority VARCHAR(40) COMMENT ''DQI-E1驱动 来源权威性：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated'' AFTER description', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'ef_completeness_scope');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN ef_completeness_scope VARCHAR(40) COMMENT ''DQI-E2驱动 组分完整性：full/minor_missing/partial_missing/major_only/unknown'' AFTER ef_source_authority', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'ef_data_region');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN ef_data_region VARCHAR(40) COMMENT ''DQI-E3驱动 地理适用性：in_boundary/same_grid/national/similar_economy/other_country'' AFTER ef_completeness_scope', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'ef_data_year');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN ef_data_year INT COMMENT ''DQI-E4驱动 因子数据年份：与核算年度差 Δt 决定时间适用性得分'' AFTER ef_data_region', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'ef_tech_applicability');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN ef_tech_applicability VARCHAR(40) COMMENT ''DQI-E5驱动 技术工况适用性：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default'' AFTER ef_data_year', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'ef_conversion_chain');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN ef_conversion_chain VARCHAR(40) COMMENT ''DQI-E6驱动 单位换算链可靠性：direct_match/standard_single/multi_step/derived_from_other/unclear'' AFTER ef_tech_applicability', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'dqi_e1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN dqi_e1_score TINYINT COMMENT ''DQI-E1 来源权威性得分（1-5）'' AFTER ef_conversion_chain', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'dqi_e2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN dqi_e2_score TINYINT COMMENT ''DQI-E2 组分完整性得分（1-5）'' AFTER dqi_e1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'dqi_e3_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN dqi_e3_score TINYINT COMMENT ''DQI-E3 地理适用性得分（1-5）'' AFTER dqi_e2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'dqi_e4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN dqi_e4_score TINYINT COMMENT ''DQI-E4 时间适用性得分（1-5）'' AFTER dqi_e3_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'dqi_e5_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN dqi_e5_score TINYINT COMMENT ''DQI-E5 技术工况适用性得分（1-5）'' AFTER dqi_e4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_emission_factor' AND column_name = 'dqi_e6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_emission_factor ADD COLUMN dqi_e6_score TINYINT COMMENT ''DQI-E6 单位换算链可靠性得分（1-5）'' AFTER dqi_e5_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 3) emission_thermal_emission_factor（热力排放因子库表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'ef_source_authority');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN ef_source_authority VARCHAR(40) COMMENT ''DQI-E1驱动 来源权威性：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated'' AFTER description', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'ef_completeness_scope');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN ef_completeness_scope VARCHAR(40) COMMENT ''DQI-E2驱动 组分完整性：full/minor_missing/partial_missing/major_only/unknown'' AFTER ef_source_authority', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'ef_data_region');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN ef_data_region VARCHAR(40) COMMENT ''DQI-E3驱动 地理适用性：in_boundary/same_grid/national/similar_economy/other_country'' AFTER ef_completeness_scope', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'ef_data_year');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN ef_data_year INT COMMENT ''DQI-E4驱动 因子数据年份：与核算年度差 Δt 决定时间适用性得分'' AFTER ef_data_region', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'ef_tech_applicability');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN ef_tech_applicability VARCHAR(40) COMMENT ''DQI-E5驱动 技术工况适用性：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default'' AFTER ef_data_year', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'ef_conversion_chain');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN ef_conversion_chain VARCHAR(40) COMMENT ''DQI-E6驱动 单位换算链可靠性：direct_match/standard_single/multi_step/derived_from_other/unclear'' AFTER ef_tech_applicability', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'dqi_e1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN dqi_e1_score TINYINT COMMENT ''DQI-E1 来源权威性得分（1-5）'' AFTER ef_conversion_chain', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'dqi_e2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN dqi_e2_score TINYINT COMMENT ''DQI-E2 组分完整性得分（1-5）'' AFTER dqi_e1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'dqi_e3_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN dqi_e3_score TINYINT COMMENT ''DQI-E3 地理适用性得分（1-5）'' AFTER dqi_e2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'dqi_e4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN dqi_e4_score TINYINT COMMENT ''DQI-E4 时间适用性得分（1-5）'' AFTER dqi_e3_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'dqi_e5_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN dqi_e5_score TINYINT COMMENT ''DQI-E5 技术工况适用性得分（1-5）'' AFTER dqi_e4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_thermal_emission_factor' AND column_name = 'dqi_e6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_thermal_emission_factor ADD COLUMN dqi_e6_score TINYINT COMMENT ''DQI-E6 单位换算链可靠性得分（1-5）'' AFTER dqi_e5_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 4) emission_waste_incineration_factor（固体废弃物焚烧排放因子表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'ef_source_authority');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN ef_source_authority VARCHAR(40) COMMENT ''DQI-E1驱动 来源权威性：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated'' AFTER description', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'ef_completeness_scope');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN ef_completeness_scope VARCHAR(40) COMMENT ''DQI-E2驱动 组分完整性：full/minor_missing/partial_missing/major_only/unknown'' AFTER ef_source_authority', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'ef_data_region');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN ef_data_region VARCHAR(40) COMMENT ''DQI-E3驱动 地理适用性：in_boundary/same_grid/national/similar_economy/other_country'' AFTER ef_completeness_scope', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'ef_data_year');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN ef_data_year INT COMMENT ''DQI-E4驱动 因子数据年份：与核算年度差 Δt 决定时间适用性得分'' AFTER ef_data_region', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'ef_tech_applicability');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN ef_tech_applicability VARCHAR(40) COMMENT ''DQI-E5驱动 技术工况适用性：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default'' AFTER ef_data_year', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'ef_conversion_chain');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN ef_conversion_chain VARCHAR(40) COMMENT ''DQI-E6驱动 单位换算链可靠性：direct_match/standard_single/multi_step/derived_from_other/unclear'' AFTER ef_tech_applicability', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'dqi_e1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN dqi_e1_score TINYINT COMMENT ''DQI-E1 来源权威性得分（1-5）'' AFTER ef_conversion_chain', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'dqi_e2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN dqi_e2_score TINYINT COMMENT ''DQI-E2 组分完整性得分（1-5）'' AFTER dqi_e1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'dqi_e3_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN dqi_e3_score TINYINT COMMENT ''DQI-E3 地理适用性得分（1-5）'' AFTER dqi_e2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'dqi_e4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN dqi_e4_score TINYINT COMMENT ''DQI-E4 时间适用性得分（1-5）'' AFTER dqi_e3_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'dqi_e5_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN dqi_e5_score TINYINT COMMENT ''DQI-E5 技术工况适用性得分（1-5）'' AFTER dqi_e4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_waste_incineration_factor' AND column_name = 'dqi_e6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_waste_incineration_factor ADD COLUMN dqi_e6_score TINYINT COMMENT ''DQI-E6 单位换算链可靠性得分（1-5）'' AFTER dqi_e5_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 5) emission_collection_node_data（各采集节点本次核算结果表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_a1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_a1_score TINYINT COMMENT ''DQI-A1 计量来源可靠性得分（1-5）：取自采集点表'' AFTER data_missing_description', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_a2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_a2_score TINYINT COMMENT ''DQI-A2 计量器具有效性得分（1-5）：取自采集点表'' AFTER dqi_a1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_a4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_a4_score TINYINT COMMENT ''DQI-A4 分摊与边界匹配得分（1-5）：取自采集点表'' AFTER dqi_a2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_a6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_a6_score TINYINT COMMENT ''DQI-A6 数据采集质量得分（1-5）：取自采集点表'' AFTER dqi_a4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_e1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_e1_score TINYINT COMMENT ''DQI-E1 来源权威性得分（1-5）：取自本次采用的排放因子'' AFTER dqi_a6_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_e2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_e2_score TINYINT COMMENT ''DQI-E2 组分完整性得分（1-5）：取自本次采用的排放因子'' AFTER dqi_e1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_e3_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_e3_score TINYINT COMMENT ''DQI-E3 地理适用性得分（1-5）：取自本次采用的排放因子'' AFTER dqi_e2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_e4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_e4_score TINYINT COMMENT ''DQI-E4 时间适用性得分（1-5）：取自本次采用的排放因子'' AFTER dqi_e3_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_e5_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_e5_score TINYINT COMMENT ''DQI-E5 技术工况适用性得分（1-5）：取自本次采用的排放因子'' AFTER dqi_e4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_collection_node_data' AND column_name = 'dqi_e6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_collection_node_data ADD COLUMN dqi_e6_score TINYINT COMMENT ''DQI-E6 单位换算链可靠性得分（1-5）：取自本次采用的排放因子'' AFTER dqi_e5_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
