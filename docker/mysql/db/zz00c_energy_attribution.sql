-- 能耗归属站点/区间目录及三类采集点归属字段。
-- 本迁移不回填历史采集点，不修改或删除 energy_allocation；重复执行安全。

SET NAMES utf8mb4;

INSERT INTO emission_data_dict (dict_code, dict_name, description, sort_order)
SELECT 'shuohuang_railway_line', '朔黄铁路管辖线路', '朔黄铁路管辖的线路列表，用于能耗归属站点/区间选择', 11
WHERE NOT EXISTS (SELECT 1 FROM emission_data_dict WHERE dict_code='shuohuang_railway_line');

SET @line_dict_id=(SELECT id FROM emission_data_dict WHERE dict_code='shuohuang_railway_line' ORDER BY id LIMIT 1);
INSERT INTO emission_data_dict_item (dict_id,item_code,item_value,sort_order,status)
SELECT @line_dict_id,'shuohuang','朔黄线',1,1
WHERE NOT EXISTS (SELECT 1 FROM emission_data_dict_item WHERE dict_id=@line_dict_id AND item_code='shuohuang');
INSERT INTO emission_data_dict_item (dict_id,item_code,item_value,sort_order,status)
SELECT @line_dict_id,'huangwan','黄万线',2,1
WHERE NOT EXISTS (SELECT 1 FROM emission_data_dict_item WHERE dict_id=@line_dict_id AND item_code='huangwan');

-- 稳定编码是线路字典的业务主键。修复曾被错误客户端字符集写入的中文值，
-- 同时保证重复执行时不会增加字典或字典项。
UPDATE emission_data_dict
SET dict_name='朔黄铁路管辖线路',
    description='朔黄铁路管辖的线路列表，用于能耗归属站点/区间选择'
WHERE dict_code='shuohuang_railway_line';

UPDATE emission_data_dict_item
SET item_value=CASE item_code
    WHEN 'shuohuang' THEN '朔黄线'
    WHEN 'huangwan' THEN '黄万线'
    ELSE item_value END
WHERE dict_id=@line_dict_id AND item_code IN ('shuohuang','huangwan');

CREATE TABLE IF NOT EXISTS emission_energy_attribution_station (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    name VARCHAR(60) NOT NULL COMMENT '站点/区间名称',
    pinyin_code VARCHAR(30) COMMENT '名称拼音首字母，用于快速查询',
    line_name VARCHAR(60) COMMENT '所属线路名称',
    branch_company VARCHAR(60) COMMENT '所属分公司',
    created_by BIGINT COMMENT '创建人ID',
    updated_by BIGINT COMMENT '更新人ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    KEY idx_energy_attr_pinyin (pinyin_code),
    KEY idx_energy_attr_line (line_name),
    KEY idx_energy_attr_branch (branch_company)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='能耗归属站点/区间设置表';

-- CREATE TABLE IF NOT EXISTS 不会更新已存在表的注释，因此显式修正本迁移创建的元数据。
ALTER TABLE emission_energy_attribution_station
    MODIFY COLUMN name VARCHAR(60) NOT NULL COMMENT '站点/区间名称',
    MODIFY COLUMN pinyin_code VARCHAR(30) NULL COMMENT '名称拼音首字母，用于快速查询',
    MODIFY COLUMN line_name VARCHAR(60) NULL COMMENT '所属线路名称',
    MODIFY COLUMN branch_company VARCHAR(60) NULL COMMENT '所属分公司',
    COMMENT='能耗归属站点/区间设置表';

-- 兼容修复：早期版本未声明客户端字符集，UTF-8文本曾被按latin1解释后再次写入UTF-8列。
-- 仅转换能够无损还原、还原结果合法且确实发生变化的值；正确中文转换时会产生“?”，因此不会被更新。
UPDATE emission_energy_attribution_station
SET name=CONVERT(CAST(CONVERT(name USING latin1) AS BINARY) USING utf8mb4)
WHERE name IS NOT NULL
  AND LOCATE('3F', HEX(CONVERT(name USING latin1)))=0
  AND CONVERT(CAST(CONVERT(name USING latin1) AS BINARY) USING utf8mb4) IS NOT NULL
  AND BINARY name <> BINARY CONVERT(CAST(CONVERT(name USING latin1) AS BINARY) USING utf8mb4);

UPDATE emission_energy_attribution_station
SET line_name=CONVERT(CAST(CONVERT(line_name USING latin1) AS BINARY) USING utf8mb4)
WHERE line_name IS NOT NULL
  AND LOCATE('3F', HEX(CONVERT(line_name USING latin1)))=0
  AND CONVERT(CAST(CONVERT(line_name USING latin1) AS BINARY) USING utf8mb4) IS NOT NULL
  AND BINARY line_name <> BINARY CONVERT(CAST(CONVERT(line_name USING latin1) AS BINARY) USING utf8mb4);

UPDATE emission_energy_attribution_station
SET branch_company=CONVERT(CAST(CONVERT(branch_company USING latin1) AS BINARY) USING utf8mb4)
WHERE branch_company IS NOT NULL
  AND LOCATE('3F', HEX(CONVERT(branch_company USING latin1)))=0
  AND CONVERT(CAST(CONVERT(branch_company USING latin1) AS BINARY) USING utf8mb4) IS NOT NULL
  AND BINARY branch_company <> BINARY CONVERT(CAST(CONVERT(branch_company USING latin1) AS BINARY) USING utf8mb4);

INSERT INTO emission_energy_attribution_station (name,pinyin_code,line_name,branch_company)
SELECT seed.name,seed.pinyin_code,seed.line_name,seed.branch_company
FROM (
SELECT '神池南站区' name,'SCNZQ' pinyin_code,'朔黄线' line_name,'原平分公司' branch_company UNION ALL
SELECT '宁武西站区','NWXZQ','朔黄线','原平分公司' UNION ALL SELECT '龙宫站区','LGZQ','朔黄线','原平分公司' UNION ALL
SELECT '北大牛站区','BDNZQ','朔黄线','原平分公司' UNION ALL SELECT '原平南站区','YPNZQ','朔黄线','原平分公司' UNION ALL
SELECT '回凤站区','HFZQ','朔黄线','原平分公司' UNION ALL SELECT '东冶站区','DYZQ','朔黄线','原平分公司' UNION ALL
SELECT '南湾站区','NWZQ','朔黄线','原平分公司' UNION ALL SELECT '滴流磴站区','DLDZQ','朔黄线','原平分公司' UNION ALL
SELECT '猴刎站区','HWZQ','朔黄线','原平分公司' UNION ALL SELECT '小觉站区','XJZQ','朔黄线','原平分公司' UNION ALL
SELECT '古月站区','GYZQ','朔黄线','原平分公司' UNION ALL SELECT '西柏坡站区','XBPZQ','朔黄线','原平分公司' UNION ALL
SELECT '三汲站区','SJZQ','朔黄线','肃宁分公司' UNION ALL SELECT '灵寿站区','LSZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '行唐站区','HTZQ','朔黄线','肃宁分公司' UNION ALL SELECT '新曲站区','XQZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '定州西站区','DZXZQ','朔黄线','肃宁分公司' UNION ALL SELECT '定州东站区','DZDZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '安国站区','AGZQ','朔黄线','肃宁分公司' UNION ALL SELECT '博野站区','BYZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '蠡县站区','LXZQ','朔黄线','肃宁分公司' UNION ALL SELECT '肃宁北Ⅱ场站区','SNBCZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '太师庄站区','TSZZQ','朔黄线','肃宁分公司' UNION ALL SELECT '河间站区','HJZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '行别营站区','XBYZQ','朔黄线','肃宁分公司' UNION ALL SELECT '黎民居站区','LMJZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '杜生站区','DSZQ','朔黄线','肃宁分公司' UNION ALL SELECT '沧州西站区','CZXZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '李天木站区','LTMZQ','朔黄线','肃宁分公司' UNION ALL SELECT '黄骅南站区','HHNZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '段庄站区','DZZQ','朔黄线','肃宁分公司' UNION ALL SELECT '黄骅港站区','HHGZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '港口Ⅰ场站区','GKCZQ','朔黄线','肃宁分公司' UNION ALL
SELECT '黄骅南站区','HHNZQ','黄万线','肃宁分公司' UNION ALL SELECT '黄骅东站区','HHDZQ','黄万线','肃宁分公司' UNION ALL
SELECT '羊三木站区','YSMZQ','黄万线','肃宁分公司' UNION ALL SELECT '窦庄子站区','DZZZQ','黄万线','肃宁分公司' UNION ALL
SELECT '郭庄子站区','GZZZQ','黄万线','肃宁分公司' UNION ALL SELECT '北港农场站区','BGNCZQ','黄万线','肃宁分公司' UNION ALL
SELECT '大港水库站区','DGSKZQ','黄万线','肃宁分公司' UNION ALL SELECT '万家码头站区','WJMTZQ','黄万线','肃宁分公司' UNION ALL
SELECT '黄骅港折返段','HHGZFD','朔黄线','机辆分公司' UNION ALL SELECT '东营西折返段','DYXZFD','朔黄线','机辆分公司' UNION ALL
SELECT '西柏坡折返段','XBPZFD','朔黄线','机辆分公司' UNION ALL SELECT '神池南折返段','SCNZFD','朔黄线','机辆分公司' UNION ALL
SELECT '肃宁分公司机关','SNFSGJ',NULL,'肃宁分公司' UNION ALL SELECT '肃宁分公司直属','SNFSZS',NULL,'肃宁分公司' UNION ALL
SELECT '原平分公司机关','YPFSGJ',NULL,'原平分公司' UNION ALL SELECT '原平分公司直属','YPFSZS',NULL,'原平分公司' UNION ALL
SELECT '机辆分公司机关','JLFSGJ',NULL,'机辆分公司' UNION ALL SELECT '机辆分公司直属','JLFSZS',NULL,'机辆分公司'
) seed
WHERE NOT EXISTS (SELECT 1 FROM emission_energy_attribution_station s WHERE s.name=seed.name
  AND s.line_name <=> seed.line_name AND s.branch_company <=> seed.branch_company);

-- MySQL 5.7/8.0 均可重复执行的列、索引和外键创建。
SET @schema_name=DATABASE();

SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='emission_meter_info' AND column_name='energy_attribution_station_id'),'SELECT 1','ALTER TABLE emission_meter_info ADD COLUMN energy_attribution_station_id BIGINT NULL COMMENT ''能耗归属站点/区间ID'' AFTER energy_allocation'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='emission_meter_info' AND column_name='energy_attribution_dept_id'),'SELECT 1','ALTER TABLE emission_meter_info ADD COLUMN energy_attribution_dept_id BIGINT NULL COMMENT ''能耗归属部门ID'' AFTER energy_attribution_station_id'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='emission_fossil_fuel_meter_info' AND column_name='energy_attribution_station_id'),'SELECT 1','ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN energy_attribution_station_id BIGINT NULL COMMENT ''能耗归属站点/区间ID'' AFTER energy_allocation'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='emission_fossil_fuel_meter_info' AND column_name='energy_attribution_dept_id'),'SELECT 1','ALTER TABLE emission_fossil_fuel_meter_info ADD COLUMN energy_attribution_dept_id BIGINT NULL COMMENT ''能耗归属部门ID'' AFTER energy_attribution_station_id'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='emission_purchased_heat_meter_info' AND column_name='energy_attribution_station_id'),'SELECT 1','ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN energy_attribution_station_id BIGINT NULL COMMENT ''能耗归属站点/区间ID'' AFTER energy_allocation'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=@schema_name AND table_name='emission_purchased_heat_meter_info' AND column_name='energy_attribution_dept_id'),'SELECT 1','ALTER TABLE emission_purchased_heat_meter_info ADD COLUMN energy_attribution_dept_id BIGINT NULL COMMENT ''能耗归属部门ID'' AFTER energy_attribution_station_id'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=@schema_name AND table_name='emission_meter_info' AND index_name='idx_meter_energy_attr_station'),'SELECT 1','ALTER TABLE emission_meter_info ADD INDEX idx_meter_energy_attr_station (energy_attribution_station_id)'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=@schema_name AND table_name='emission_meter_info' AND index_name='idx_meter_energy_attr_dept'),'SELECT 1','ALTER TABLE emission_meter_info ADD INDEX idx_meter_energy_attr_dept (energy_attribution_dept_id)'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=@schema_name AND table_name='emission_fossil_fuel_meter_info' AND index_name='idx_fossil_energy_attr_station'),'SELECT 1','ALTER TABLE emission_fossil_fuel_meter_info ADD INDEX idx_fossil_energy_attr_station (energy_attribution_station_id)'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=@schema_name AND table_name='emission_fossil_fuel_meter_info' AND index_name='idx_fossil_energy_attr_dept'),'SELECT 1','ALTER TABLE emission_fossil_fuel_meter_info ADD INDEX idx_fossil_energy_attr_dept (energy_attribution_dept_id)'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=@schema_name AND table_name='emission_purchased_heat_meter_info' AND index_name='idx_heat_energy_attr_station'),'SELECT 1','ALTER TABLE emission_purchased_heat_meter_info ADD INDEX idx_heat_energy_attr_station (energy_attribution_station_id)'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.statistics WHERE table_schema=@schema_name AND table_name='emission_purchased_heat_meter_info' AND index_name='idx_heat_energy_attr_dept'),'SELECT 1','ALTER TABLE emission_purchased_heat_meter_info ADD INDEX idx_heat_energy_attr_dept (energy_attribution_dept_id)'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.key_column_usage WHERE table_schema=@schema_name AND table_name='emission_meter_info' AND column_name='energy_attribution_station_id' AND referenced_table_name='emission_energy_attribution_station'),'SELECT 1','ALTER TABLE emission_meter_info ADD CONSTRAINT fk_meter_energy_attr_station FOREIGN KEY (energy_attribution_station_id) REFERENCES emission_energy_attribution_station(id) ON DELETE RESTRICT'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.key_column_usage WHERE table_schema=@schema_name AND table_name='emission_fossil_fuel_meter_info' AND column_name='energy_attribution_station_id' AND referenced_table_name='emission_energy_attribution_station'),'SELECT 1','ALTER TABLE emission_fossil_fuel_meter_info ADD CONSTRAINT fk_fossil_energy_attr_station FOREIGN KEY (energy_attribution_station_id) REFERENCES emission_energy_attribution_station(id) ON DELETE RESTRICT'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl=(SELECT IF(EXISTS(SELECT 1 FROM information_schema.key_column_usage WHERE table_schema=@schema_name AND table_name='emission_purchased_heat_meter_info' AND column_name='energy_attribution_station_id' AND referenced_table_name='emission_energy_attribution_station'),'SELECT 1','ALTER TABLE emission_purchased_heat_meter_info ADD CONSTRAINT fk_heat_energy_attr_station FOREIGN KEY (energy_attribution_station_id) REFERENCES emission_energy_attribution_station(id) ON DELETE RESTRICT'));
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
