-- Freeze formal-factor provenance and DQI together with every collection-node override.
-- Existing overrides are intentionally not guessed or rewritten; they must be reselected.
SET NAMES utf8mb4;
SET @db := DATABASE();

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_source')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_source VARCHAR(30) NULL COMMENT ''节点覆盖因子来源：ELECTRICITY/FOSSIL/THERMAL'' AFTER carbon_emission_factor_description', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_id')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_id BIGINT NULL COMMENT ''节点覆盖所选正式因子主键，仅用于来源追踪'' AFTER carbon_emission_factor_source', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_name')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_name VARCHAR(200) NULL COMMENT ''节点覆盖所选正式因子名称快照'' AFTER carbon_emission_factor_id', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_data_year')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_data_year INT NULL COMMENT ''节点覆盖所选正式因子数据年份快照'' AFTER carbon_emission_factor_name', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_dqi_e1_score')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_dqi_e1_score TINYINT NULL COMMENT ''节点覆盖因子DQI-E1快照（1-5）'' AFTER carbon_emission_factor_data_year', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_dqi_e2_score')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_dqi_e2_score TINYINT NULL COMMENT ''节点覆盖因子DQI-E2快照（1-5）'' AFTER carbon_emission_factor_dqi_e1_score', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_dqi_e3_score')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_dqi_e3_score TINYINT NULL COMMENT ''节点覆盖因子DQI-E3快照（1-5）'' AFTER carbon_emission_factor_dqi_e2_score', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_dqi_e4_score')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_dqi_e4_score TINYINT NULL COMMENT ''节点覆盖因子固定DQI-E4快照（1-5，可由数据年份动态计算）'' AFTER carbon_emission_factor_dqi_e3_score', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_dqi_e5_score')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_dqi_e5_score TINYINT NULL COMMENT ''节点覆盖因子DQI-E5快照（1-5）'' AFTER carbon_emission_factor_dqi_e4_score', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_node_config' AND column_name='carbon_emission_factor_dqi_e6_score')=0, 'ALTER TABLE emission_node_config ADD COLUMN carbon_emission_factor_dqi_e6_score TINYINT NULL COMMENT ''节点覆盖因子DQI-E6快照（1-5）'' AFTER carbon_emission_factor_dqi_e5_score', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Deployment preflight: these legacy snapshots remain untouched but cannot pass
-- template validation until a user reselects a formal factor.
SELECT node_id, carbon_emission_factor, carbon_emission_factor_unit,
       carbon_emission_factor_description
FROM emission_node_config
WHERE carbon_emission_factor IS NOT NULL
  AND (carbon_emission_factor_source IS NULL OR carbon_emission_factor_id IS NULL)
ORDER BY node_id;
