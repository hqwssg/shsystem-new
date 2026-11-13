-- ============================================================
-- 更新脚本 2026-10-20
-- 变更：三张采集点表（emission_meter_info 电表 / emission_fossil_fuel_meter_info
--       化石燃料 / emission_purchased_heat_meter_info 外购热能）新增 DQI 评分维度
--       字段，每表 8 列：
--         驱动字段：ad_metering_tier(A1计量来源可靠性)
--                  ad_meter_calibration(A2计量器具有效性)
--                  ad_geo_basis(A4分摊与边界匹配)
--                  ad_data_collection_quality(A6数据采集质量，1-5直接评分)
--         维度得分：dqi_a1_score / dqi_a2_score / dqi_a4_score / dqi_a6_score
--       用途：采集点级评分信息相对固定，碳排放核算后由不确定性分析模块
--       （DQI+MCS）沿用表内记录自动评分，无需逐次人工打分。
--       （A5 时间同步性按数据年份差动态计算、EF 侧为排放因子属性，均不属于
--        采集点固定属性，不纳入。）
-- 幂等：逐列判断是否已存在，可重复执行；不修改存量采集点数据。
-- ============================================================

-- ------------------------------------------------------------
-- 1) emission_meter_info（电表信息表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'ad_metering_tier');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN ad_metering_tier VARCHAR(40) COMMENT ''DQI-A1驱动 计量来源可靠性：online_meter/manual_ledger/statistical_report/literature_thirdparty/default_or_estimated'' AFTER auto_meter_reading_config', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'ad_meter_calibration');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN ad_meter_calibration VARCHAR(40) COMMENT ''DQI-A2驱动 计量器具有效性：calib_valid_cert/calib_valid_internal/calib_overdue_verified/calib_overdue_no_record/calib_status_unknown/calib_not_applicable'' AFTER ad_metering_tier', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'ad_geo_basis');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN ad_geo_basis VARCHAR(40) COMMENT ''DQI-A4驱动 分摊与边界匹配：direct_metered/ledger_complete/allocated/analogized/default_value'' AFTER ad_meter_calibration', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'ad_data_collection_quality');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN ad_data_collection_quality INT COMMENT ''DQI-A6驱动 数据采集质量：1-5直接评分'' AFTER ad_geo_basis', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'dqi_a1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN dqi_a1_score TINYINT COMMENT ''DQI-A1 计量来源可靠性得分（1-5）'' AFTER ad_data_collection_quality', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'dqi_a2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN dqi_a2_score TINYINT COMMENT ''DQI-A2 计量器具有效性得分（1-5）'' AFTER dqi_a1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'dqi_a4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN dqi_a4_score TINYINT COMMENT ''DQI-A4 分摊与边界匹配得分（1-5）'' AFTER dqi_a2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_meter_info' AND column_name = 'dqi_a6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_meter_info ADD COLUMN dqi_a6_score TINYINT COMMENT ''DQI-A6 数据采集质量得分（1-5）'' AFTER dqi_a4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2) emission_fossil_fuel_meter_info（化石燃料用量信息表采集点表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'ad_metering_tier');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN ad_metering_tier VARCHAR(40) COMMENT ''DQI-A1驱动 计量来源可靠性：online_meter/manual_ledger/statistical_report/literature_thirdparty/default_or_estimated'' AFTER auto_meter_reading_config', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'ad_meter_calibration');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN ad_meter_calibration VARCHAR(40) COMMENT ''DQI-A2驱动 计量器具有效性：calib_valid_cert/calib_valid_internal/calib_overdue_verified/calib_overdue_no_record/calib_status_unknown/calib_not_applicable'' AFTER ad_metering_tier', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'ad_geo_basis');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN ad_geo_basis VARCHAR(40) COMMENT ''DQI-A4驱动 分摊与边界匹配：direct_metered/ledger_complete/allocated/analogized/default_value'' AFTER ad_meter_calibration', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'ad_data_collection_quality');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN ad_data_collection_quality INT COMMENT ''DQI-A6驱动 数据采集质量：1-5直接评分'' AFTER ad_geo_basis', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'dqi_a1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN dqi_a1_score TINYINT COMMENT ''DQI-A1 计量来源可靠性得分（1-5）'' AFTER ad_data_collection_quality', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'dqi_a2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN dqi_a2_score TINYINT COMMENT ''DQI-A2 计量器具有效性得分（1-5）'' AFTER dqi_a1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'dqi_a4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN dqi_a4_score TINYINT COMMENT ''DQI-A4 分摊与边界匹配得分（1-5）'' AFTER dqi_a2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_fossil_fuel_meter_info' AND column_name = 'dqi_a6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN dqi_a6_score TINYINT COMMENT ''DQI-A6 数据采集质量得分（1-5）'' AFTER dqi_a4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 3) emission_purchased_heat_meter_info（外购热能用量信息表采集点表）
-- ------------------------------------------------------------
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'ad_metering_tier');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN ad_metering_tier VARCHAR(40) COMMENT ''DQI-A1驱动 计量来源可靠性：online_meter/manual_ledger/statistical_report/literature_thirdparty/default_or_estimated'' AFTER auto_meter_reading_config', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'ad_meter_calibration');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN ad_meter_calibration VARCHAR(40) COMMENT ''DQI-A2驱动 计量器具有效性：calib_valid_cert/calib_valid_internal/calib_overdue_verified/calib_overdue_no_record/calib_status_unknown/calib_not_applicable'' AFTER ad_metering_tier', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'ad_geo_basis');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN ad_geo_basis VARCHAR(40) COMMENT ''DQI-A4驱动 分摊与边界匹配：direct_metered/ledger_complete/allocated/analogized/default_value'' AFTER ad_meter_calibration', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'ad_data_collection_quality');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN ad_data_collection_quality INT COMMENT ''DQI-A6驱动 数据采集质量：1-5直接评分'' AFTER ad_geo_basis', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'dqi_a1_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN dqi_a1_score TINYINT COMMENT ''DQI-A1 计量来源可靠性得分（1-5）'' AFTER ad_data_collection_quality', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'dqi_a2_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN dqi_a2_score TINYINT COMMENT ''DQI-A2 计量器具有效性得分（1-5）'' AFTER dqi_a1_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'dqi_a4_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN dqi_a4_score TINYINT COMMENT ''DQI-A4 分摊与边界匹配得分（1-5）'' AFTER dqi_a2_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE table_schema = DATABASE() AND table_name = 'emission_purchased_heat_meter_info' AND column_name = 'dqi_a6_score');
SET @sql := IF(@c = 0, 'ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN dqi_a6_score TINYINT COMMENT ''DQI-A6 数据采集质量得分（1-5）'' AFTER dqi_a4_score', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
