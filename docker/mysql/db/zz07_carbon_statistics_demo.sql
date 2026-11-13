-- Idempotent 24-month statistics dataset shared by the statistics page and GoView.
SET NAMES utf8mb4;
SET @statistics_user_id := COALESCE((SELECT user_id FROM sys_user WHERE user_name='admin' LIMIT 1), 1);

-- The deployment schema creates table structures first. Seed the node types here as well so
-- this fixture also works on a newly initialized database, and resolve IDs by name because
-- existing installations may not use the original auto-increment values.
INSERT IGNORE INTO emission_node_type(type_name,can_have_children,description) VALUES
  ('root',TRUE,'根节点'),
  ('data_collection',FALSE,'排放数据采集点');
SET @statistics_root_type := (SELECT id FROM emission_node_type WHERE type_name='root' LIMIT 1);
SET @statistics_data_type := (SELECT id FROM emission_node_type WHERE type_name='data_collection' LIMIT 1);

-- Keep the three demonstration factors calculable even when a deployment started from the
-- structure-only update schema and therefore does not yet contain model dictionary seeds.
INSERT IGNORE INTO emission_data_dict(dict_code,dict_name,description,sort_order,status)
VALUES ('emission_subcategory','排放数据小类','统计查询示例所需的排放数据分类',2,1);
SET @statistics_subcategory_dict := (
  SELECT id FROM emission_data_dict WHERE dict_code='emission_subcategory' LIMIT 1
);
INSERT INTO emission_data_dict_item(dict_id,item_code,item_value,parent_code,sort_order,status)
SELECT @statistics_subcategory_dict,x.item_code,x.item_value,x.parent_code,x.sort_order,1
FROM (
  SELECT 'PE_PF' item_code,'外购电力' item_value,'PE' parent_code,1 sort_order
  UNION ALL SELECT 'FF_D','柴油','FF',20
  UNION ALL SELECT 'PH_HD','热力数据','PH',30
) x
WHERE NOT EXISTS(
  SELECT 1 FROM emission_data_dict_item i
  WHERE i.dict_id=@statistics_subcategory_dict AND i.item_code=x.item_code
);

INSERT IGNORE INTO emission_unit_standard
  (unit_code,unit_name,unit_category,physical_quantity,is_base,sort_order,status) VALUES
  ('kWh','千瓦时(kWh)','ELECTRIC','ENERGY',1,1,1),
  ('GJ','吉焦(GJ)','HEAT','ENERGY',1,3,1),
  ('L','升(L)','LIQUID_FUEL','VOLUME',1,6,1),
  ('kg','千克(kg)','SOLID_FUEL','MASS',1,9,1),
  ('t','吨(t)','SOLID_FUEL','MASS',0,10,1);
INSERT IGNORE INTO emission_ghg_unit
  (ghg_code,ghg_name,ghg_type,mass_unit_code,sort_order,status) VALUES
  ('kgCO2','千克二氧化碳(kgCO₂)','CO2','kg',1,1),
  ('tCO2','吨二氧化碳(tCO₂)','CO2','t',2,1);
INSERT IGNORE INTO emission_factor_unit
  (factor_unit_code,factor_unit_name,numerator_ghg_code,denominator_unit_code,subcategory_code,sort_order,status) VALUES
  ('kgCO2_per_kWh','kgCO₂/kWh','kgCO2','kWh','PE_PF',1,1),
  ('tCO2_per_t_FF_D','tCO₂/t','tCO2','t','FF_D',1,1),
  ('tCO2_per_GJ_HD','tCO₂/GJ','tCO2','GJ','PH_HD',1,1);
INSERT IGNORE INTO emission_unit_conversion
  (subcategory_code,from_unit_code,to_unit_code,conversion_factor,remark) VALUES
  ('FF_D','L','t',0.00085000,'柴油密度约0.85 kg/L');

INSERT INTO emission_station_interval(name,pinyin_code,description,sort_order,status,created_by,updated_by)
SELECT '统计示例-定州西站','STAT-DZX','统计查询与大屏演示专用电力站点',120000,1,@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_station_interval WHERE pinyin_code='STAT-DZX');
SET @statistics_station := (SELECT id FROM emission_station_interval WHERE pinyin_code='STAT-DZX' ORDER BY (name='统计示例-定州西站') DESC,id DESC LIMIT 1);

INSERT INTO emission_concentrator(name,pinyin_code,station_interval_id,concentrator_address,description,sort_order,status,created_by,updated_by)
SELECT '统计示例-定州西站集中器','STAT-DZX-C1',@statistics_station,'STAT-DZX-C1','统计演示集中器',120000,1,@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_concentrator WHERE pinyin_code='STAT-DZX-C1');
SET @statistics_concentrator := (SELECT id FROM emission_concentrator WHERE pinyin_code='STAT-DZX-C1' ORDER BY (name='统计示例-定州西站集中器') DESC,id DESC LIMIT 1);

INSERT INTO emission_meter_info
  (name,pinyin_code,point_id,meter_address,meter_type,meter_model,purpose_description,parent_meter_id,
   is_cumulative,is_mobile_source,measurement_unit,data_source_system,billing_cycle_unit,
   billing_cycle_start_date,billing_cycle_length,emission_subcategory,meter_reading_method,
   sort_order,status,energy_use_category,created_by,updated_by)
SELECT '统计示例-牵引用电自动采集','STAT-ELECTRICITY',@statistics_concentrator,'STAT-E-001',
       '综合电力监测仪表','三相四线智能电表','统计与GoView演示用月度牵引用电',0,
       0,0,'kWh','统计示例数据',2,1,1,'PE_PF',1,120000,1,'生产用能',@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_meter_info WHERE pinyin_code='STAT-ELECTRICITY');
SET @statistics_electricity := (SELECT id FROM emission_meter_info WHERE pinyin_code='STAT-ELECTRICITY' ORDER BY (name='统计示例-牵引用电自动采集') DESC,id DESC LIMIT 1);

INSERT INTO emission_fossil_fuel_collection_scope(scope_name,pinyin_code,sort_order,description,status,created_by,updated_by)
SELECT '统计示例-运输燃料范围','STAT-FOSSIL',120000,'统计查询与大屏演示专用燃料范围',1,@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_fossil_fuel_collection_scope WHERE pinyin_code='STAT-FOSSIL');
SET @statistics_fossil_scope := (SELECT id FROM emission_fossil_fuel_collection_scope WHERE pinyin_code='STAT-FOSSIL' ORDER BY (scope_name='统计示例-运输燃料范围') DESC,id DESC LIMIT 1);

INSERT INTO emission_fossil_fuel_collection_sub_scope
  (sub_scope_name,pinyin_code,collection_scope_id,sort_order,description,status,created_by,updated_by)
SELECT '统计示例-内燃机车柴油','STAT-DIESEL',@statistics_fossil_scope,1,'内燃机车柴油月度统计示例',1,@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_fossil_fuel_collection_sub_scope WHERE pinyin_code='STAT-DIESEL');
SET @statistics_fossil_sub_scope := (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE pinyin_code='STAT-DIESEL' ORDER BY (sub_scope_name='统计示例-内燃机车柴油') DESC,id DESC LIMIT 1);

INSERT INTO emission_fossil_fuel_meter_info
  (name,pinyin_code,sub_scope_id,emission_subcategory,meter_model,purpose_description,parent_meter_id,
   is_cumulative,is_mobile_source,measurement_unit,data_source_system,billing_cycle_unit,
   billing_cycle_start_date,billing_cycle_length,meter_reading_method,sort_order,status,
   energy_use,created_by,updated_by)
SELECT '统计示例-内燃机车柴油人工采集','STAT-DIESEL-M1',@statistics_fossil_sub_scope,'FF_D','燃料计量表',
       '统计与GoView演示用月度柴油消耗',0,0,1,'L','统计示例数据',2,1,1,0,120000,1,
       '生产用能',@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_fossil_fuel_meter_info WHERE pinyin_code='STAT-DIESEL-M1');
SET @statistics_diesel := (SELECT id FROM emission_fossil_fuel_meter_info WHERE pinyin_code='STAT-DIESEL-M1' ORDER BY (name='统计示例-内燃机车柴油人工采集') DESC,id DESC LIMIT 1);

INSERT INTO emission_purchased_heat_collection_scope(scope_name,pinyin_code,sort_order,description,created_by,updated_by)
SELECT '统计示例-站房供热范围','STAT-HEAT',120000,'统计查询与大屏演示专用供热范围',@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_purchased_heat_collection_scope WHERE pinyin_code='STAT-HEAT');
SET @statistics_heat_scope := (SELECT id FROM emission_purchased_heat_collection_scope WHERE pinyin_code='STAT-HEAT' ORDER BY (scope_name='统计示例-站房供热范围') DESC,id DESC LIMIT 1);

INSERT INTO emission_purchased_heat_collection_sub_scope
  (sub_scope_name,pinyin_code,collection_scope_id,description,created_by,updated_by)
SELECT '统计示例-站房外购热力','STAT-HEAT-S1',@statistics_heat_scope,'站房外购热力月度统计示例',@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_purchased_heat_collection_sub_scope WHERE pinyin_code='STAT-HEAT-S1');
SET @statistics_heat_sub_scope := (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE pinyin_code='STAT-HEAT-S1' ORDER BY (sub_scope_name='统计示例-站房外购热力') DESC,id DESC LIMIT 1);

INSERT INTO emission_purchased_heat_meter_info
  (name,pinyin_code,sub_scope_id,emission_subcategory,meter_model,purpose_description,parent_meter_id,
   is_cumulative,is_mobile_source,measurement_unit,data_source_system,billing_cycle_unit,
   billing_cycle_start_date,billing_cycle_length,meter_reading_method,sort_order,status,
   energy_use,created_by,updated_by)
SELECT '统计示例-站房热力自动采集','STAT-HEAT-M1',@statistics_heat_sub_scope,'PH_HD','热能计量表',
       '统计与GoView演示用月度外购热力',0,0,0,'GJ','统计示例数据',2,1,1,1,120000,1,
       '生产辅助用能',@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_purchased_heat_meter_info WHERE pinyin_code='STAT-HEAT-M1');
SET @statistics_heat := (SELECT id FROM emission_purchased_heat_meter_info WHERE pinyin_code='STAT-HEAT-M1' ORDER BY (name='统计示例-站房热力自动采集') DESC,id DESC LIMIT 1);

INSERT INTO emission_template(name,description,created_by,updated_by,version,enabled,template_type,task_config,check_result)
SELECT '统计查询与GoView演示模板','电力、柴油、外购热力近24个月统计演示数据',@statistics_user_id,@statistics_user_id,
       1,1,2,'{"fixtureCode":"STATISTICS_DEMO","cycleType":"MONTHLY","executionTime":"02:00","startDate":"2024-01-01","endDate":"2099-12-31"}',1
WHERE NOT EXISTS(SELECT 1 FROM emission_template WHERE name='统计查询与GoView演示模板'
  OR JSON_UNQUOTE(JSON_EXTRACT(task_config,'$.fixtureCode'))='STATISTICS_DEMO');
SET @statistics_template := (SELECT id FROM emission_template
  WHERE name='统计查询与GoView演示模板' OR JSON_UNQUOTE(JSON_EXTRACT(task_config,'$.fixtureCode'))='STATISTICS_DEMO'
  ORDER BY (name='统计查询与GoView演示模板') DESC,id DESC LIMIT 1);
UPDATE emission_template
SET task_config=JSON_SET(COALESCE(NULLIF(task_config,''),'{}'),'$.fixtureCode','STATISTICS_DEMO')
WHERE id=@statistics_template;

INSERT INTO emission_node(name,type_id,parent_id,template_id,source_node_id,sort_order,created_by,updated_by)
SELECT '统计示例-朔黄铁路碳排放',@statistics_root_type,NULL,@statistics_template,0,1,@statistics_user_id,@statistics_user_id
WHERE NOT EXISTS(SELECT 1 FROM emission_node WHERE template_id=@statistics_template AND name='统计示例-朔黄铁路碳排放');
SET @statistics_root := (SELECT id FROM emission_node WHERE template_id=@statistics_template AND name='统计示例-朔黄铁路碳排放' LIMIT 1);

INSERT INTO emission_node(name,type_id,parent_id,template_id,source_node_id,sort_order,created_by,updated_by)
SELECT x.name,@statistics_data_type,@statistics_root,@statistics_template,0,x.sort_order,@statistics_user_id,@statistics_user_id
FROM (
  SELECT '统计示例-牵引用电' name,1 sort_order UNION ALL
  SELECT '统计示例-内燃机车柴油',2 UNION ALL
  SELECT '统计示例-站房外购热力',3
) x
WHERE NOT EXISTS(SELECT 1 FROM emission_node n WHERE n.template_id=@statistics_template AND n.name=x.name);
SET @statistics_electricity_node := (SELECT id FROM emission_node WHERE template_id=@statistics_template AND name='统计示例-牵引用电' LIMIT 1);
SET @statistics_diesel_node := (SELECT id FROM emission_node WHERE template_id=@statistics_template AND name='统计示例-内燃机车柴油' LIMIT 1);
SET @statistics_heat_node := (SELECT id FROM emission_node WHERE template_id=@statistics_template AND name='统计示例-站房外购热力' LIMIT 1);

INSERT INTO emission_node_config
  (node_id,emission_category,emission_subcategory,carbon_emission_factor,carbon_emission_factor_unit,
   carbon_emission_factor_description,collection_description,equipment_code,collection_point_type,
   collection_point_id,collection_point_status,created_by,updated_by)
SELECT x.node_id,x.category,x.subcategory,x.factor,x.factor_unit,x.factor_description,x.description,
       x.code,x.point_type,x.point_id,1,@statistics_user_id,@statistics_user_id
FROM (
  SELECT @statistics_electricity_node node_id,'PE' category,'PE_PF' subcategory,0.570300 factor,
         'kgCO₂/kWh' factor_unit,'示例电网排放因子' factor_description,
         '统计示例电力采集' description,'STAT-E-001' code,1 point_type,@statistics_electricity point_id
  UNION ALL SELECT @statistics_diesel_node,'FF','FF_D',3.170000,'tCO₂/t','示例柴油排放因子',
         '统计示例柴油采集','STAT-F-001',2,@statistics_diesel
  UNION ALL SELECT @statistics_heat_node,'PH','PH_HD',0.110000,'tCO₂/GJ','示例外购热力排放因子',
         '统计示例热力采集','STAT-H-001',3,@statistics_heat
) x
WHERE NOT EXISTS(SELECT 1 FROM emission_node_config c WHERE c.node_id=x.node_id);

-- Normalize older fixture keys that included database-generated point IDs. This keeps the
-- dataset stable even if a database is rebuilt and receives different auto-increment IDs.
DELETE FROM emission_collection_record
WHERE external_record_id LIKE 'STAT-DEMO-%'
  AND NOT (
    (collection_point_type=1 AND collection_point_id=@statistics_electricity)
    OR (collection_point_type=2 AND collection_point_id=@statistics_diesel)
    OR (collection_point_type=3 AND collection_point_id=@statistics_heat)
  );
UPDATE emission_collection_record
SET external_record_id=CONCAT('STAT-DEMO-',collection_point_type,'-',DATE_FORMAT(collection_time,'%Y%m'))
WHERE external_record_id LIKE 'STAT-DEMO-%';
DELETE duplicate_record
FROM emission_collection_record duplicate_record
JOIN emission_collection_record retained_record
  ON retained_record.external_record_id=duplicate_record.external_record_id
 AND retained_record.id < duplicate_record.id
WHERE duplicate_record.external_record_id LIKE 'STAT-DEMO-%';

-- Keep this fixture at exactly three points x 24 rolling months. Previous versions
-- retained the oldest three records after a month rollover, growing from 72 to 75.
-- Only fixture-owned STAT-DEMO records are trimmed; business records are untouched.
SET @statistics_window_start := DATE_SUB(
  STR_TO_DATE(DATE_FORMAT(CURDATE(),'%Y-%m-01'),'%Y-%m-%d'),
  INTERVAL 23 MONTH
);
SET @statistics_window_end := DATE_ADD(LAST_DAY(CURDATE()),INTERVAL 1 DAY);
DELETE FROM emission_collection_record
WHERE external_record_id LIKE 'STAT-DEMO-%'
  AND (collection_time < @statistics_window_start OR collection_time >= @statistics_window_end);

-- Rolling 24 months. external_record_id makes reruns and future monthly updates idempotent.
INSERT INTO emission_collection_record
  (collection_point_type,collection_point_id,reading_value,external_record_id,external_quality,
   collection_time,collection_status,workflow_status,submitter_id,submitted_at,reviewer_id,reviewed_at,
   review_comment,last_fetch_time,collection_point_name,emission_subcategory,measurement_unit,
   meter_reading_method,is_cumulative,billing_cycle_start_date,billing_cycle_end_date,created_by,updated_by)
SELECT p.point_type,p.point_id,
       CASE p.point_type
         WHEN 1 THEN 108000 + MOD(MONTH(d.period_date) * 730 + d.month_offset * 190,18000)
         WHEN 2 THEN 11800 + MOD(MONTH(d.period_date) * 137 + d.month_offset * 53,2600)
         ELSE 430 + MOD(MONTH(d.period_date) * 19 + d.month_offset * 7,140)
       END,
       CONCAT('STAT-DEMO-',p.point_type,'-',DATE_FORMAT(d.period_date,'%Y%m')),
       CASE WHEN MOD(d.month_offset,6)=0 THEN 'NORMAL' ELSE 'HIGH' END,
       TIMESTAMP(LAST_DAY(d.period_date),'23:00:00'),1,'APPROVED',@statistics_user_id,
       TIMESTAMP(LAST_DAY(d.period_date),'23:05:00'),@statistics_user_id,
       TIMESTAMP(LAST_DAY(d.period_date),'23:10:00'),'统计演示数据自动审核通过',
       TIMESTAMP(LAST_DAY(d.period_date),'23:05:00'),p.point_name,p.subcategory,p.unit,p.reading_method,0,
       STR_TO_DATE(DATE_FORMAT(d.period_date,'%Y-%m-01'),'%Y-%m-%d'),LAST_DAY(d.period_date),
       @statistics_user_id,@statistics_user_id
FROM (
  SELECT 1 point_type,@statistics_electricity point_id,'统计示例-牵引用电自动采集' point_name,'PE_PF' subcategory,'kWh' unit,1 reading_method
  UNION ALL SELECT 2,@statistics_diesel,'统计示例-内燃机车柴油人工采集','FF_D','L',0
  UNION ALL SELECT 3,@statistics_heat,'统计示例-站房热力自动采集','PH_HD','GJ',1
) p
CROSS JOIN (
  SELECT offsets.month_offset,DATE_SUB(CURDATE(),INTERVAL offsets.month_offset MONTH) period_date
  FROM (
    SELECT 0 month_offset UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
    UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11
    UNION ALL SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL SELECT 16 UNION ALL SELECT 17
    UNION ALL SELECT 18 UNION ALL SELECT 19 UNION ALL SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23
  ) offsets
) d
WHERE p.point_id IS NOT NULL
  AND NOT EXISTS(
    SELECT 1 FROM emission_collection_record r
    WHERE r.external_record_id=CONCAT('STAT-DEMO-',p.point_type,'-',DATE_FORMAT(d.period_date,'%Y%m'))
  );
