-- 中文节点与采集点示例数据，脚本可重复执行。
-- 覆盖购入电力、化石燃料、外购热能，以及自动采集和手工录入。
SET NAMES utf8mb4;

SET @sample_user_id := COALESCE((SELECT user_id FROM sys_user WHERE user_name = 'admin' LIMIT 1), 1);
SET @sample_dept_id := COALESCE((SELECT dept_id FROM sys_user WHERE user_name = 'admin' LIMIT 1), 3000);

-- 将上一版英文演示数据改为中文名称，避免管理界面同时出现英文演示数据。
UPDATE emission_station_interval SET name = '示例-旧定州西站', description = '旧版示例电力站点' WHERE name = 'DEMO-Suning-DingzhouWest-Station' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_station_interval WHERE name = '示例-旧定州西站') x);
UPDATE emission_concentrator SET name = '示例-旧定州西站集中器', description = '旧版示例电力集中器' WHERE name = 'DEMO-DingzhouWest-Concentrator' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_concentrator WHERE name = '示例-旧定州西站集中器') x);
UPDATE emission_meter_info SET name = '示例-旧定州西站自动电表', purpose_description = '旧版示例自动采集电表' WHERE name = 'DEMO-DingzhouWest-AutoMeter' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_meter_info WHERE name = '示例-旧定州西站自动电表') x);
UPDATE emission_meter_info SET name = '示例-旧定州西站手工电表', purpose_description = '旧版示例手工录入电表' WHERE name = 'DEMO-DingzhouWest-ManualMeter' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_meter_info WHERE name = '示例-旧定州西站手工电表') x);
UPDATE emission_fossil_fuel_collection_scope SET scope_name = '示例-旧化石燃料范围', description = '旧版示例化石燃料范围' WHERE scope_name = 'DEMO-Suning-Fossil' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_fossil_fuel_collection_scope WHERE scope_name = '示例-旧化石燃料范围') x);
UPDATE emission_fossil_fuel_collection_sub_scope SET sub_scope_name = '示例-旧轨道车柴油' WHERE sub_scope_name = 'DEMO-Rail-Diesel' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = '示例-旧轨道车柴油') x);
UPDATE emission_fossil_fuel_collection_sub_scope SET sub_scope_name = '示例-旧汽车用汽油' WHERE sub_scope_name = 'DEMO-Automobile-Gasoline' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = '示例-旧汽车用汽油') x);
UPDATE emission_fossil_fuel_collection_sub_scope SET sub_scope_name = '示例-旧汽车用柴油' WHERE sub_scope_name = 'DEMO-Automobile-Diesel' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = '示例-旧汽车用柴油') x);
UPDATE emission_fossil_fuel_meter_info SET name = '示例-旧轨道车柴油计量点', purpose_description = '旧版示例轨道车柴油采集点' WHERE name = 'DEMO-Rail-Diesel-Meter' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_fossil_fuel_meter_info WHERE name = '示例-旧轨道车柴油计量点') x);
UPDATE emission_purchased_heat_collection_scope SET scope_name = '示例-旧外购热能范围', description = '旧版示例外购热能范围' WHERE scope_name = 'DEMO-Suning-Heat' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_purchased_heat_collection_scope WHERE scope_name = '示例-旧外购热能范围') x);
UPDATE emission_purchased_heat_collection_sub_scope SET sub_scope_name = '示例-旧生产车间供热' WHERE sub_scope_name = 'DEMO-Suning-Workshop-Heating' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE sub_scope_name = '示例-旧生产车间供热') x);
UPDATE emission_purchased_heat_collection_sub_scope SET sub_scope_name = '示例-旧办公区供热' WHERE sub_scope_name = 'DEMO-Suning-Office-Heating' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE sub_scope_name = '示例-旧办公区供热') x);
UPDATE emission_purchased_heat_meter_info SET name = '示例-旧生产车间热能表', purpose_description = '旧版示例外购热能采集点' WHERE name = 'DEMO-Suning-Workshop-HeatMeter' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_purchased_heat_meter_info WHERE name = '示例-旧生产车间热能表') x);
UPDATE emission_template SET name = '示例-旧三类能源核算模板', description = '旧版示例三类能源核算模板' WHERE name = 'DEMO-Suning-Three-Domain-Model' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_template WHERE name = '示例-旧三类能源核算模板') x);
UPDATE emission_node SET name = '示例-旧肃宁分公司核算根节点' WHERE name = 'DEMO-Suning-Calculation' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_node WHERE name = '示例-旧肃宁分公司核算根节点') x);
UPDATE emission_node SET name = '示例-旧购入电力节点' WHERE name = 'DEMO-Electricity-Collection' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_node WHERE name = '示例-旧购入电力节点') x);
UPDATE emission_node SET name = '示例-旧化石燃料节点' WHERE name = 'DEMO-Fossil-Collection' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_node WHERE name = '示例-旧化石燃料节点') x);
UPDATE emission_node SET name = '示例-旧外购热能节点' WHERE name = 'DEMO-Heat-Collection' AND NOT EXISTS (SELECT 1 FROM (SELECT id FROM emission_node WHERE name = '示例-旧外购热能节点') x);
UPDATE emission_collection_record SET collection_point_name = '示例-旧定州西站自动电表' WHERE collection_point_name = 'DEMO-DingzhouWest-AutoMeter';
UPDATE emission_collection_record SET collection_point_name = '示例-旧轨道车柴油计量点' WHERE collection_point_name = 'DEMO-Rail-Diesel-Meter';

-- 电力：三个站点、三个集中器、四个电表，分别覆盖自动和手工录入。
INSERT INTO emission_station_interval
    (name, pinyin_code, description, sort_order, status, created_by, updated_by)
SELECT x.name, x.code, x.description, x.sort_order, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-肃宁分公司定州西站' name, 'SN-DZX' code, '肃宁分公司定州西站电力采集站点' description, 910 sort_order
    UNION ALL SELECT '示例-肃宁分公司定州东站', 'SN-DZD', '肃宁分公司定州东站电力采集站点', 911
    UNION ALL SELECT '示例-肃宁分公司望都站', 'SN-WDZ', '肃宁分公司望都站电力采集站点', 912
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_station_interval s WHERE s.name = x.name);

SET @station_west := (SELECT id FROM emission_station_interval WHERE name = '示例-肃宁分公司定州西站' LIMIT 1);
SET @station_east := (SELECT id FROM emission_station_interval WHERE name = '示例-肃宁分公司定州东站' LIMIT 1);
SET @station_wangdu := (SELECT id FROM emission_station_interval WHERE name = '示例-肃宁分公司望都站' LIMIT 1);

INSERT INTO emission_concentrator
    (name, pinyin_code, station_interval_id, concentrator_address, description, sort_order, status, created_by, updated_by)
SELECT x.name, x.code, x.station_id, x.address, x.description, x.sort_order, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-定州西站一号集中器' name, 'SN-DZX-C1' code, @station_west station_id, 'DZX-C1' address, '定州西站主变及办公区电表集中器' description, 910 sort_order
    UNION ALL SELECT '示例-定州东站信号集中器', 'SN-DZD-C1', @station_east, 'DZD-C1', '定州东站信号设备电表集中器', 911
    UNION ALL SELECT '示例-望都站生产集中器', 'SN-WDZ-C1', @station_wangdu, 'WDZ-C1', '望都站生产用电表集中器', 912
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_concentrator c WHERE c.name = x.name);

SET @concentrator_west := (SELECT id FROM emission_concentrator WHERE name = '示例-定州西站一号集中器' LIMIT 1);
SET @concentrator_east := (SELECT id FROM emission_concentrator WHERE name = '示例-定州东站信号集中器' LIMIT 1);
SET @concentrator_wangdu := (SELECT id FROM emission_concentrator WHERE name = '示例-望都站生产集中器' LIMIT 1);

INSERT INTO emission_meter_info
    (name, pinyin_code, point_id, meter_address, meter_type, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, emission_subcategory,
     meter_reading_method, sort_order, status, created_by, updated_by)
SELECT x.name, x.code, x.point_id, x.address, '综合电力监测仪表', x.model, x.description,
       0, x.cumulative, 0, 'kWh', '示例采集系统', 2, 1, 1, 'purchased-electricity',
       x.reading_method, x.sort_order, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-定州西站主变电表' name, 'SN-DZX-M1' code, @concentrator_west point_id, 'DZX-M1' address, '三相四线智能电表' model, '自动采集主变用电量' description, 1 cumulative, 1 reading_method, 910 sort_order
    UNION ALL SELECT '示例-定州西站办公用电表', 'SN-DZX-M2', @concentrator_west, 'DZX-M2', '三相四线智能电表', '手工录入办公区域用电量', 0, 0, 911
    UNION ALL SELECT '示例-定州东站信号电表', 'SN-DZD-M1', @concentrator_east, 'DZD-M1', '综合电力监测仪表', '自动采集信号设备用电量', 1, 1, 912
    UNION ALL SELECT '示例-望都站生产用电表', 'SN-WDZ-M1', @concentrator_wangdu, 'WDZ-M1', '三相四线智能电表', '手工录入生产设备用电量', 0, 0, 913
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_meter_info m WHERE m.name = x.name);

SET @electric_auto_west := (SELECT id FROM emission_meter_info WHERE name = '示例-定州西站主变电表' LIMIT 1);
SET @electric_manual_west := (SELECT id FROM emission_meter_info WHERE name = '示例-定州西站办公用电表' LIMIT 1);
SET @electric_auto_east := (SELECT id FROM emission_meter_info WHERE name = '示例-定州东站信号电表' LIMIT 1);
SET @electric_manual_wangdu := (SELECT id FROM emission_meter_info WHERE name = '示例-望都站生产用电表' LIMIT 1);

-- 化石能源：肃宁分公司下设汽车汽油、汽车柴油、轨道车柴油三个分类。
INSERT INTO emission_fossil_fuel_collection_scope
    (scope_name, pinyin_code, sort_order, description, status, created_by, updated_by)
SELECT '示例-肃宁分公司化石燃料范围', 'SN-FOSSIL', 920, '肃宁分公司化石能源采集范围', 1, @sample_user_id, @sample_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_collection_scope WHERE scope_name = '示例-肃宁分公司化石燃料范围');
SET @fossil_scope := (SELECT id FROM emission_fossil_fuel_collection_scope WHERE scope_name = '示例-肃宁分公司化石燃料范围' LIMIT 1);

INSERT INTO emission_fossil_fuel_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, sort_order, description, status, created_by, updated_by)
SELECT x.name, x.code, @fossil_scope, x.sort_order, x.description, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-汽车用汽油' name, 'SN-F-GAS' code, 1 sort_order, '运输生产部公务车辆汽油' description
    UNION ALL SELECT '示例-汽车用柴油', 'SN-F-DIESEL', 2, '运输生产部公务车辆柴油'
    UNION ALL SELECT '示例-轨道车用柴油', 'SN-F-RAIL', 3, '线路维护工队和综合工队轨道车柴油'
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_collection_sub_scope s WHERE s.sub_scope_name = x.name);

SET @fossil_gas := (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = '示例-汽车用汽油' LIMIT 1);
SET @fossil_diesel := (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = '示例-汽车用柴油' LIMIT 1);
SET @fossil_rail := (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = '示例-轨道车用柴油' LIMIT 1);

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, purpose_description, parent_meter_id,
     is_cumulative, is_mobile_source, measurement_unit, data_source_system, billing_cycle_unit,
     billing_cycle_start_date, billing_cycle_length, meter_reading_method, sort_order, status, created_by, updated_by)
SELECT x.name, x.code, x.sub_scope_id, x.subcategory, x.description, 0, 0, 1, 'L', '示例采集系统', 2, 1, 1,
       x.reading_method, x.sort_order, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-公务车辆汽油计量点' name, 'SN-F-GAS-M1' code, @fossil_gas sub_scope_id, 'gasoline' subcategory, '手工录入公务车辆汽油消耗量' description, 0 reading_method, 920 sort_order
    UNION ALL SELECT '示例-公务车辆柴油计量点', 'SN-F-DIESEL-M1', @fossil_diesel, 'diesel', '自动采集公务车辆柴油消耗量', 1, 921
    UNION ALL SELECT '示例-线路维护工队轨道车柴油计量点', 'SN-F-RAIL-M1', @fossil_rail, 'diesel', '自动采集线路维护工队轨道车柴油消耗量', 1, 922
    UNION ALL SELECT '示例-综合工队备用柴油计量点', 'SN-F-RAIL-M2', @fossil_rail, 'diesel', '手工录入综合工队备用柴油消耗量', 0, 923
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_meter_info m WHERE m.name = x.name);

SET @fossil_auto := (SELECT id FROM emission_fossil_fuel_meter_info WHERE name = '示例-线路维护工队轨道车柴油计量点' LIMIT 1);
SET @fossil_manual := (SELECT id FROM emission_fossil_fuel_meter_info WHERE name = '示例-公务车辆汽油计量点' LIMIT 1);

-- 外购热能：办公区、车站房屋、生产车间三个细分范围。
INSERT INTO emission_purchased_heat_collection_scope
    (scope_name, pinyin_code, sort_order, description, created_by, updated_by)
SELECT '示例-肃宁分公司外购热能范围', 'SN-HEAT', 930, '肃宁分公司外购热能采集范围', @sample_user_id, @sample_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_purchased_heat_collection_scope WHERE scope_name = '示例-肃宁分公司外购热能范围');
SET @heat_scope := (SELECT id FROM emission_purchased_heat_collection_scope WHERE scope_name = '示例-肃宁分公司外购热能范围' LIMIT 1);

INSERT INTO emission_purchased_heat_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, description, created_by, updated_by)
SELECT x.name, x.code, @heat_scope, x.description, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-肃宁办公区供热' name, 'SN-H-OFFICE' code, '肃宁办公区外购热能' description
    UNION ALL SELECT '示例-定州西站房屋供热', 'SN-H-STATION', '定州西站房屋外购热能'
    UNION ALL SELECT '示例-生产车间供热', 'SN-H-WORKSHOP', '生产车间外购热能'
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_purchased_heat_collection_sub_scope s WHERE s.sub_scope_name = x.name);

SET @heat_office := (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE sub_scope_name = '示例-肃宁办公区供热' LIMIT 1);
SET @heat_station := (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE sub_scope_name = '示例-定州西站房屋供热' LIMIT 1);
SET @heat_workshop := (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE sub_scope_name = '示例-生产车间供热' LIMIT 1);

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, purpose_description, parent_meter_id,
     is_cumulative, is_mobile_source, measurement_unit, data_source_system, billing_cycle_unit,
     billing_cycle_start_date, billing_cycle_length, meter_reading_method, sort_order, status, created_by, updated_by)
SELECT x.name, x.code, x.sub_scope_id, 'purchased-heat', x.description, 0, 1, 0, 'GJ', '示例采集系统', 2, 1, 1,
       x.reading_method, x.sort_order, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-肃宁办公楼外购热能表' name, 'SN-H-OFFICE-M1' code, @heat_office sub_scope_id, '自动采集肃宁办公楼外购热能' description, 1 reading_method, 930 sort_order
    UNION ALL SELECT '示例-定州西站房屋外购热能表', 'SN-H-STATION-M1', @heat_station, '手工录入定州西站房屋外购热能', 0, 931
    UNION ALL SELECT '示例-生产车间外购热能表', 'SN-H-WORKSHOP-M1', @heat_workshop, '自动采集生产车间外购热能', 1, 932
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_purchased_heat_meter_info m WHERE m.name = x.name);

SET @heat_auto := (SELECT id FROM emission_purchased_heat_meter_info WHERE name = '示例-肃宁办公楼外购热能表' LIMIT 1);
SET @heat_manual := (SELECT id FROM emission_purchased_heat_meter_info WHERE name = '示例-定州西站房屋外购热能表' LIMIT 1);

-- 中文核算模板：一个根节点和十个细分采集节点。
INSERT INTO emission_template
    (name, description, created_by, updated_by, version, enabled, template_type, task_config, check_result)
SELECT '示例-肃宁分公司三类能源核算模板', '覆盖购入电力、化石燃料和外购热能的中文核算示例',
       @sample_user_id, @sample_user_id, 1, 1, 2,
       '{"cycleType":"MONTHLY","executionTime":"02:00","startDate":"2026-01-01","endDate":"2099-12-31"}', 1
WHERE NOT EXISTS (SELECT 1 FROM emission_template WHERE name = '示例-肃宁分公司三类能源核算模板');
SET @sample_template := (SELECT id FROM emission_template WHERE name = '示例-肃宁分公司三类能源核算模板' LIMIT 1);

INSERT INTO emission_node (name, type_id, parent_id, template_id, source_node_id, sort_order, created_by, updated_by)
SELECT '示例-肃宁分公司碳排放核算', 1, NULL, @sample_template, 0, 1, @sample_user_id, @sample_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE template_id=@sample_template AND name='示例-肃宁分公司碳排放核算');
SET @sample_root := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-肃宁分公司碳排放核算' LIMIT 1);

INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description, created_by, updated_by)
SELECT @sample_root, 'SN-SAMPLE', '肃宁分公司示例', 1, 'COMPANY', '肃宁分公司三类能源核算边界', @sample_user_id, @sample_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id=@sample_root);

INSERT INTO emission_node (name, type_id, parent_id, template_id, source_node_id, sort_order, created_by, updated_by)
SELECT x.name, 3, @sample_root, @sample_template, 0, x.sort_order, @sample_user_id, @sample_user_id
FROM (
    SELECT '示例-定州西站主变购入电力' name, 1 sort_order UNION ALL
    SELECT '示例-定州西站办公区购入电力', 2 UNION ALL
    SELECT '示例-定州东站信号设备购入电力', 3 UNION ALL
    SELECT '示例-望都站生产用电', 4 UNION ALL
    SELECT '示例-公务车辆汽油', 5 UNION ALL
    SELECT '示例-公务车辆柴油', 6 UNION ALL
    SELECT '示例-线路维护工队轨道车柴油', 7 UNION ALL
    SELECT '示例-综合工队备用柴油', 8 UNION ALL
    SELECT '示例-肃宁办公区外购热能', 9 UNION ALL
    SELECT '示例-定州西站房屋外购热能', 10 UNION ALL
    SELECT '示例-生产车间外购热能', 11
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_node n WHERE n.template_id=@sample_template AND n.name=x.name);

SET @node_e1 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-定州西站主变购入电力' LIMIT 1);
SET @node_e2 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-定州西站办公区购入电力' LIMIT 1);
SET @node_e3 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-定州东站信号设备购入电力' LIMIT 1);
SET @node_e4 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-望都站生产用电' LIMIT 1);
SET @node_f1 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-公务车辆汽油' LIMIT 1);
SET @node_f2 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-公务车辆柴油' LIMIT 1);
SET @node_f3 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-线路维护工队轨道车柴油' LIMIT 1);
SET @node_f4 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-综合工队备用柴油' LIMIT 1);
SET @node_h1 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-肃宁办公区外购热能' LIMIT 1);
SET @node_h2 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-定州西站房屋外购热能' LIMIT 1);
SET @node_h3 := (SELECT id FROM emission_node WHERE template_id=@sample_template AND name='示例-生产车间外购热能' LIMIT 1);

INSERT INTO emission_node_config
    (node_id, emission_category, emission_subcategory, collection_description, equipment_code,
     collection_point_type, collection_point_id, collection_point_status, created_by, updated_by)
SELECT x.node_id, x.category, x.subcategory, x.description, x.equipment_code, x.point_type, x.point_id, 1, @sample_user_id, @sample_user_id
FROM (
    SELECT @node_e1 node_id, 'electricity' category, 'purchased-electricity' subcategory, '自动采集定州西站主变购入电力' description, 'SN-E-001' equipment_code, 1 point_type, @electric_auto_west point_id
    UNION ALL SELECT @node_e2, 'electricity', 'purchased-electricity', '手工录入定州西站办公区购入电力', 'SN-E-002', 1, @electric_manual_west
    UNION ALL SELECT @node_e3, 'electricity', 'purchased-electricity', '自动采集定州东站信号设备购入电力', 'SN-E-003', 1, @electric_auto_east
    UNION ALL SELECT @node_e4, 'electricity', 'purchased-electricity', '手工录入望都站生产用电', 'SN-E-004', 1, @electric_manual_wangdu
    UNION ALL SELECT @node_f1, 'fossil-fuel', 'gasoline', '手工录入公务车辆汽油', 'SN-F-001', 2, @fossil_manual
    UNION ALL SELECT @node_f2, 'fossil-fuel', 'diesel', '自动采集公务车辆柴油', 'SN-F-002', 2, (SELECT id FROM emission_fossil_fuel_meter_info WHERE name='示例-公务车辆柴油计量点' LIMIT 1)
    UNION ALL SELECT @node_f3, 'fossil-fuel', 'diesel', '自动采集线路维护工队轨道车柴油', 'SN-F-003', 2, @fossil_auto
    UNION ALL SELECT @node_f4, 'fossil-fuel', 'diesel', '手工录入综合工队备用柴油', 'SN-F-004', 2, (SELECT id FROM emission_fossil_fuel_meter_info WHERE name='示例-综合工队备用柴油计量点' LIMIT 1)
    UNION ALL SELECT @node_h1, 'purchased-heat', 'purchased-heat', '自动采集肃宁办公区外购热能', 'SN-H-001', 3, @heat_auto
    UNION ALL SELECT @node_h2, 'purchased-heat', 'purchased-heat', '手工录入定州西站房屋外购热能', 'SN-H-002', 3, @heat_manual
    UNION ALL SELECT @node_h3, 'purchased-heat', 'purchased-heat', '自动采集生产车间外购热能', 'SN-H-003', 3, (SELECT id FROM emission_purchased_heat_meter_info WHERE name='示例-生产车间外购热能表' LIMIT 1)
) x
WHERE NOT EXISTS (SELECT 1 FROM emission_node_config c WHERE c.node_id=x.node_id);

-- 为三个能源范围建立公司级读写授权，便于管理员直接观察示例节点。
INSERT IGNORE INTO sys_carbon_company (dept_id, created_by, updated_by)
SELECT @sample_dept_id, @sample_user_id, @sample_user_id
WHERE EXISTS (SELECT 1 FROM sys_dept WHERE dept_id=@sample_dept_id);
INSERT IGNORE INTO sys_carbon_scope_owner (scope_type, scope_id, company_dept_id, created_by, updated_by)
SELECT 'electricity', @station_west, @sample_dept_id, @sample_user_id, @sample_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_company WHERE dept_id=@sample_dept_id);
INSERT IGNORE INTO sys_carbon_scope_owner (scope_type, scope_id, company_dept_id, created_by, updated_by)
SELECT 'fossil', @fossil_scope, @sample_dept_id, @sample_user_id, @sample_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_company WHERE dept_id=@sample_dept_id);
INSERT IGNORE INTO sys_carbon_scope_owner (scope_type, scope_id, company_dept_id, created_by, updated_by)
SELECT 'heat', (SELECT id FROM emission_purchased_heat_collection_scope WHERE scope_name='示例-肃宁分公司外购热能范围' LIMIT 1), @sample_dept_id, @sample_user_id, @sample_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_company WHERE dept_id=@sample_dept_id);

INSERT IGNORE INTO sys_carbon_scope_grant
    (scope_type, scope_id, dept_id, node_type, node_id, can_read, can_write, can_delegate, created_by, updated_by)
SELECT 'electricity', @station_west, @sample_dept_id, 'station', @station_west, 1, 1, 1, @sample_user_id, @sample_user_id
UNION ALL SELECT 'electricity', @station_east, @sample_dept_id, 'station', @station_east, 1, 1, 1, @sample_user_id, @sample_user_id
UNION ALL SELECT 'electricity', @station_wangdu, @sample_dept_id, 'station', @station_wangdu, 1, 1, 1, @sample_user_id, @sample_user_id
UNION ALL SELECT 'fossil', @fossil_scope, @sample_dept_id, 'scope', @fossil_scope, 1, 1, 1, @sample_user_id, @sample_user_id
UNION ALL SELECT 'heat', (SELECT id FROM emission_purchased_heat_collection_scope WHERE scope_name='示例-肃宁分公司外购热能范围' LIMIT 1), @sample_dept_id, 'scope', (SELECT id FROM emission_purchased_heat_collection_scope WHERE scope_name='示例-肃宁分公司外购热能范围' LIMIT 1), 1, 1, 1, @sample_user_id, @sample_user_id;

-- 为每个中文示例采集点补充一对可操作样例：节点名-自动采集、节点名-人工采集。
-- 仅匹配示例节点，避免脚本执行时向真实生产采集点批量复制数据；重复执行不会重复创建。
INSERT INTO emission_meter_info
    (name, pinyin_code, point_id, meter_address, meter_type, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, emission_subcategory,
     energy_category_l1, energy_category_l2, energy_category_l3, energy_use_category,
     energy_allocation, power_category, auto_meter_reading_config, meter_reading_method,
     parent_child_relationship, is_virtual_meter, is_allocation_child, allocation_ratio,
     sort_order, status, created_by, updated_by)
SELECT CONCAT(m.name, '-自动采集'), LEFT(CONCAT(COALESCE(m.pinyin_code, CONCAT('SAMPLE-', m.id)), '-AUTO'), 50),
       m.point_id, LEFT(CONCAT(COALESCE(m.meter_address, CONCAT('M-', m.id)), '-AUTO'), 20), m.meter_type,
       m.meter_model, CONCAT(m.purpose_description, '（自动采集示例）'), m.parent_meter_id, 1,
       m.is_mobile_source, m.measurement_unit, m.data_source_system, m.billing_cycle_unit,
       m.billing_cycle_start_date, m.billing_cycle_length, m.emission_subcategory, m.energy_category_l1,
       m.energy_category_l2, m.energy_category_l3, m.energy_use_category, m.energy_allocation,
       m.power_category, m.auto_meter_reading_config, 1, m.parent_child_relationship, m.is_virtual_meter,
       m.is_allocation_child, m.allocation_ratio, m.sort_order + 10000, 1, @sample_user_id, @sample_user_id
FROM emission_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND m.name NOT LIKE '%-自动采集'
  AND m.name NOT LIKE '%-人工采集'
  AND NOT EXISTS (SELECT 1 FROM emission_meter_info x WHERE x.name = CONCAT(m.name, '-自动采集'))
UNION ALL
SELECT CONCAT(m.name, '-人工采集'), LEFT(CONCAT(COALESCE(m.pinyin_code, CONCAT('SAMPLE-', m.id)), '-MANUAL'), 50),
       m.point_id, LEFT(CONCAT(COALESCE(m.meter_address, CONCAT('M-', m.id)), '-MANUAL'), 20), m.meter_type,
       m.meter_model, CONCAT(m.purpose_description, '（人工采集示例）'), m.parent_meter_id, 0,
       m.is_mobile_source, m.measurement_unit, m.data_source_system, m.billing_cycle_unit,
       m.billing_cycle_start_date, m.billing_cycle_length, m.emission_subcategory, m.energy_category_l1,
       m.energy_category_l2, m.energy_category_l3, m.energy_use_category, m.energy_allocation,
       m.power_category, NULL, 0, m.parent_child_relationship, m.is_virtual_meter, m.is_allocation_child,
       m.allocation_ratio, m.sort_order + 20000, 1, @sample_user_id, @sample_user_id
FROM emission_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND m.name NOT LIKE '%-自动采集'
  AND m.name NOT LIKE '%-人工采集'
  AND NOT EXISTS (SELECT 1 FROM emission_meter_info x WHERE x.name = CONCAT(m.name, '-人工采集'));

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, energy_category_l1,
     energy_category_l2, energy_category_l3, energy_use_category, energy_allocation,
     meter_reading_method, sort_order, status, created_by, updated_by)
SELECT CONCAT(m.name, '-自动采集'), LEFT(CONCAT(COALESCE(m.pinyin_code, CONCAT('SAMPLE-', m.id)), '-AUTO'), 50),
       m.sub_scope_id, m.emission_subcategory, m.meter_model, CONCAT(m.purpose_description, '（自动采集示例）'),
       m.parent_meter_id, 1, m.is_mobile_source, m.measurement_unit, m.data_source_system,
       m.billing_cycle_unit, m.billing_cycle_start_date, m.billing_cycle_length, m.energy_category_l1,
       m.energy_category_l2, m.energy_category_l3, m.energy_use_category, m.energy_allocation, 1,
       m.sort_order + 10000, 1, @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND m.name NOT LIKE '%-自动采集'
  AND m.name NOT LIKE '%-人工采集'
  AND NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_meter_info x WHERE x.name = CONCAT(m.name, '-自动采集'))
UNION ALL
SELECT CONCAT(m.name, '-人工采集'), LEFT(CONCAT(COALESCE(m.pinyin_code, CONCAT('SAMPLE-', m.id)), '-MANUAL'), 50),
       m.sub_scope_id, m.emission_subcategory, m.meter_model, CONCAT(m.purpose_description, '（人工采集示例）'),
       m.parent_meter_id, 0, m.is_mobile_source, m.measurement_unit, m.data_source_system,
       m.billing_cycle_unit, m.billing_cycle_start_date, m.billing_cycle_length, m.energy_category_l1,
       m.energy_category_l2, m.energy_category_l3, m.energy_use_category, m.energy_allocation, 0,
       m.sort_order + 20000, 1, @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND m.name NOT LIKE '%-自动采集'
  AND m.name NOT LIKE '%-人工采集'
  AND NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_meter_info x WHERE x.name = CONCAT(m.name, '-人工采集'));

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, energy_category_l1,
     energy_category_l2, energy_category_l3, energy_use_category, energy_allocation,
     meter_reading_method, sort_order, status, created_by, updated_by)
SELECT CONCAT(m.name, '-自动采集'), LEFT(CONCAT(COALESCE(m.pinyin_code, CONCAT('SAMPLE-', m.id)), '-AUTO'), 50),
       m.sub_scope_id, m.emission_subcategory, m.meter_model, CONCAT(m.purpose_description, '（自动采集示例）'),
       m.parent_meter_id, 1, m.is_mobile_source, m.measurement_unit, m.data_source_system,
       m.billing_cycle_unit, m.billing_cycle_start_date, m.billing_cycle_length, m.energy_category_l1,
       m.energy_category_l2, m.energy_category_l3, m.energy_use_category, m.energy_allocation, 1,
       m.sort_order + 10000, 1, @sample_user_id, @sample_user_id
FROM emission_purchased_heat_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND m.name NOT LIKE '%-自动采集'
  AND m.name NOT LIKE '%-人工采集'
  AND NOT EXISTS (SELECT 1 FROM emission_purchased_heat_meter_info x WHERE x.name = CONCAT(m.name, '-自动采集'))
UNION ALL
SELECT CONCAT(m.name, '-人工采集'), LEFT(CONCAT(COALESCE(m.pinyin_code, CONCAT('SAMPLE-', m.id)), '-MANUAL'), 50),
       m.sub_scope_id, m.emission_subcategory, m.meter_model, CONCAT(m.purpose_description, '（人工采集示例）'),
       m.parent_meter_id, 0, m.is_mobile_source, m.measurement_unit, m.data_source_system,
       m.billing_cycle_unit, m.billing_cycle_start_date, m.billing_cycle_length, m.energy_category_l1,
       m.energy_category_l2, m.energy_category_l3, m.energy_use_category, m.energy_allocation, 0,
       m.sort_order + 20000, 1, @sample_user_id, @sample_user_id
FROM emission_purchased_heat_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND m.name NOT LIKE '%-自动采集'
  AND m.name NOT LIKE '%-人工采集'
  AND NOT EXISTS (SELECT 1 FROM emission_purchased_heat_meter_info x WHERE x.name = CONCAT(m.name, '-人工采集'));

-- 每个新增采集点各写入一条历史记录，便于人工录入页面直接查看周期型和累加型数据。
INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 1, m.id, CASE WHEN m.meter_reading_method = 1 THEN 1200.000000 ELSE 120.000000 END,
       DATE_SUB(NOW(), INTERVAL 1 DAY), 1, DATE_SUB(NOW(), INTERVAL 1 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND (m.name LIKE '%-自动采集' OR m.name LIKE '%-人工采集')
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type=1 AND r.collection_point_id=m.id
                    AND r.meter_reading_method=m.meter_reading_method);
INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 2, m.id, CASE WHEN m.meter_reading_method = 1 THEN 860.000000 ELSE 86.000000 END,
       DATE_SUB(NOW(), INTERVAL 2 DAY), 1, DATE_SUB(NOW(), INTERVAL 2 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND (m.name LIKE '%-自动采集' OR m.name LIKE '%-人工采集')
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type=2 AND r.collection_point_id=m.id
                    AND r.meter_reading_method=m.meter_reading_method);
INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 3, m.id, CASE WHEN m.meter_reading_method = 1 THEN 420.000000 ELSE 42.000000 END,
       DATE_SUB(NOW(), INTERVAL 3 DAY), 1, DATE_SUB(NOW(), INTERVAL 3 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_purchased_heat_meter_info m
WHERE (m.name LIKE '示例-%' OR m.name LIKE 'DEMO-%' OR m.name LIKE '%示例%')
  AND (m.name LIKE '%-自动采集' OR m.name LIKE '%-人工采集')
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type=3 AND r.collection_point_id=m.id
                    AND r.meter_reading_method=m.meter_reading_method);

-- 全量补齐：真实站点/区间及公司范围均提供自动采集、人工采集两种示例。
-- 本段使用固定的“本地示例数据”来源标识，脚本可重复执行而不会重复创建。

-- 电力树：没有集中器的站点先补一个示例集中器，保证每个站点都能挂载采集点。
INSERT INTO emission_concentrator
    (name, pinyin_code, station_interval_id, concentrator_address, description,
     sort_order, status, created_by, updated_by)
SELECT LEFT(CONCAT(LEFT(s.name, 50), '-示例集中器'), 60),
       LEFT(CONCAT('STATION-', s.id, '-SAMPLE'), 30), s.id,
       LEFT(CONCAT('S-', s.id), 20), CONCAT(s.name, '示例集中器'),
       COALESCE(s.sort_order, 0) + 100000, 1, @sample_user_id, @sample_user_id
FROM emission_station_interval s
WHERE NOT EXISTS (
          SELECT 1 FROM emission_concentrator c
          WHERE c.station_interval_id = s.id
      )
  AND NOT EXISTS (
          SELECT 1 FROM emission_concentrator c
          WHERE c.name = LEFT(CONCAT(LEFT(s.name, 50), '-示例集中器'), 60)
      );

-- 每个站点/区间补一条自动采集和一条人工采集电表。
INSERT INTO emission_meter_info
    (name, pinyin_code, point_id, meter_address, meter_type, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, emission_subcategory,
     power_category, auto_meter_reading_config, meter_reading_method, parent_child_relationship,
     is_virtual_meter, is_allocation_child, allocation_ratio, sort_order, status,
     created_by, updated_by)
SELECT CONCAT(s.name, '-自动采集'), LEFT(CONCAT('STATION-', s.id, '-AUTO'), 50), p.point_id,
       LEFT(CONCAT('S-', s.id, '-A'), 20), '综合电力监测仪表', 'DTZY-示例',
       CONCAT(s.name, '-自动采集示例'), 0, 1, 0, 'kWh', '本地示例数据', 2, 1, 1,
       'purchased-electricity', '生产用电', '{"source":"fixture","mode":"auto"}', 1, 1,
       0, 0, 1.000000, COALESCE(s.sort_order, 0) + 100000, 1, @sample_user_id, @sample_user_id
FROM emission_station_interval s
JOIN (
    SELECT station_interval_id, MIN(id) AS point_id
    FROM emission_concentrator
    GROUP BY station_interval_id
) p ON p.station_interval_id = s.id
WHERE NOT EXISTS (
          SELECT 1 FROM emission_meter_info m
          WHERE m.name = CONCAT(s.name, '-自动采集')
      );

INSERT INTO emission_meter_info
    (name, pinyin_code, point_id, meter_address, meter_type, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, emission_subcategory,
     power_category, auto_meter_reading_config, meter_reading_method, parent_child_relationship,
     is_virtual_meter, is_allocation_child, allocation_ratio, sort_order, status,
     created_by, updated_by)
SELECT CONCAT(s.name, '-人工采集'), LEFT(CONCAT('STATION-', s.id, '-MANUAL'), 50), p.point_id,
       LEFT(CONCAT('S-', s.id, '-M'), 20), '综合电力监测仪表', 'DTZY-示例',
       CONCAT(s.name, '-人工采集示例'), 0, 0, 0, 'kWh', '本地示例数据', 2, 1, 1,
       'purchased-electricity', '生产用电', NULL, 0, 1, 0, 0, 1.000000,
       COALESCE(s.sort_order, 0) + 100001, 1, @sample_user_id, @sample_user_id
FROM emission_station_interval s
JOIN (
    SELECT station_interval_id, MIN(id) AS point_id
    FROM emission_concentrator
    GROUP BY station_interval_id
) p ON p.station_interval_id = s.id
WHERE NOT EXISTS (
          SELECT 1 FROM emission_meter_info m
          WHERE m.name = CONCAT(s.name, '-人工采集')
      );

-- 化石燃料：空公司范围补示例区间；所有公司下的区间都补自动/人工两个采集点。
INSERT INTO emission_fossil_fuel_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, sort_order, description,
     status, created_by, updated_by)
SELECT CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id),
       LEFT(CONCAT('SCOPE-', s.id, '-SAMPLE'), 30), s.id, 100000 + s.id,
       CONCAT(s.scope_name, '示例区间'), 1, @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_collection_scope s
WHERE NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_collection_sub_scope ss
          WHERE ss.collection_scope_id = s.id
      )
  AND NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_collection_sub_scope ss
          WHERE ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
      );

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(ss.sub_scope_name, '-自动采集'), LEFT(CONCAT('SUBSCOPE-', ss.id, '-AUTO'), 50),
       ss.id, COALESCE((SELECT m.emission_subcategory
                        FROM emission_fossil_fuel_meter_info m
                        WHERE m.sub_scope_id = ss.id LIMIT 1), 'diesel'), '燃料计量表示例',
       CONCAT(ss.sub_scope_name, '-自动采集示例'), 0, 1, 0, 'L', '本地示例数据', 2, 1, 1, 1,
       COALESCE(ss.sort_order, 0) + 100000, 1, '生产用能', '{"source":"fixture","mode":"auto"}',
       @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_collection_sub_scope ss
WHERE NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_meter_info m
          WHERE m.name = CONCAT(ss.sub_scope_name, '-自动采集')
      );

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(ss.sub_scope_name, '-人工采集'), LEFT(CONCAT('SUBSCOPE-', ss.id, '-MANUAL'), 50),
       ss.id, COALESCE((SELECT m.emission_subcategory
                        FROM emission_fossil_fuel_meter_info m
                        WHERE m.sub_scope_id = ss.id LIMIT 1), 'diesel'), '燃料计量表示例',
       CONCAT(ss.sub_scope_name, '-人工采集示例'), 0, 0, 0, 'L', '本地示例数据', 2, 1, 1, 0,
       COALESCE(ss.sort_order, 0) + 100001, 1, '生产用能', NULL,
       @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_collection_sub_scope ss
WHERE NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_meter_info m
          WHERE m.name = CONCAT(ss.sub_scope_name, '-人工采集')
      );

-- 外购热能：空公司范围补示例区间；所有公司下的区间都补自动/人工两个采集点。
INSERT INTO emission_purchased_heat_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, description, created_by, updated_by, sort_order)
SELECT CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id),
       LEFT(CONCAT('SCOPE-', s.id, '-SAMPLE'), 30), s.id,
       CONCAT(s.scope_name, '示例区间'), @sample_user_id, @sample_user_id, 100000 + s.id
FROM emission_purchased_heat_collection_scope s
WHERE NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_collection_sub_scope ss
          WHERE ss.collection_scope_id = s.id
      )
  AND NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_collection_sub_scope ss
          WHERE ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
      );

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(ss.sub_scope_name, '-自动采集'), LEFT(CONCAT('SUBSCOPE-', ss.id, '-AUTO'), 50),
       ss.id, COALESCE((SELECT m.emission_subcategory
                        FROM emission_purchased_heat_meter_info m
                        WHERE m.sub_scope_id = ss.id LIMIT 1), 'purchased-heat'), '热能计量表示例',
       CONCAT(ss.sub_scope_name, '-自动采集示例'), 0, 1, 0, 'GJ', '本地示例数据', 2, 1, 1, 1,
       COALESCE(ss.sort_order, 0) + 100000, 1, '生产用能', '{"source":"fixture","mode":"auto"}',
       @sample_user_id, @sample_user_id
FROM emission_purchased_heat_collection_sub_scope ss
WHERE NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_meter_info m
          WHERE m.name = CONCAT(ss.sub_scope_name, '-自动采集')
      );

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(ss.sub_scope_name, '-人工采集'), LEFT(CONCAT('SUBSCOPE-', ss.id, '-MANUAL'), 50),
       ss.id, COALESCE((SELECT m.emission_subcategory
                        FROM emission_purchased_heat_meter_info m
                        WHERE m.sub_scope_id = ss.id LIMIT 1), 'purchased-heat'), '热能计量表示例',
       CONCAT(ss.sub_scope_name, '-人工采集示例'), 0, 0, 0, 'GJ', '本地示例数据', 2, 1, 1, 0,
       COALESCE(ss.sort_order, 0) + 100001, 1, '生产用能', NULL,
       @sample_user_id, @sample_user_id
FROM emission_purchased_heat_collection_sub_scope ss
WHERE NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_meter_info m
          WHERE m.name = CONCAT(ss.sub_scope_name, '-人工采集')
      );

-- 为本段新建的采集点写入一条成功历史，便于人工数据录入界面直接展示周期/累加明细。
INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 1, m.id, CASE WHEN m.meter_reading_method = 1 THEN 1200.000000 ELSE 120.000000 END,
       DATE_SUB(NOW(), INTERVAL 1 DAY), 1, DATE_SUB(NOW(), INTERVAL 1 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_meter_info m
WHERE m.data_source_system = '本地示例数据'
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type = 1 AND r.collection_point_id = m.id);

INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 2, m.id, CASE WHEN m.meter_reading_method = 1 THEN 860.000000 ELSE 86.000000 END,
       DATE_SUB(NOW(), INTERVAL 2 DAY), 1, DATE_SUB(NOW(), INTERVAL 2 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_meter_info m
WHERE m.data_source_system = '本地示例数据'
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type = 2 AND r.collection_point_id = m.id);

INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 3, m.id, CASE WHEN m.meter_reading_method = 1 THEN 420.000000 ELSE 42.000000 END,
       DATE_SUB(NOW(), INTERVAL 3 DAY), 1, DATE_SUB(NOW(), INTERVAL 3 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_purchased_heat_meter_info m
WHERE m.data_source_system = '本地示例数据'
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type = 3 AND r.collection_point_id = m.id);

-- 公司级命名补齐：公司节点本身也提供“公司名-自动采集/人工采集”示例。
-- 采集点仍挂在专用示例区间下，以保持现有树结构的范围→区间→采集点层级。
INSERT INTO emission_fossil_fuel_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, sort_order, description,
     status, created_by, updated_by)
SELECT CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id),
       LEFT(CONCAT('SCOPE-', s.id, '-COMPANY'), 30), s.id, 110000 + s.id,
       CONCAT(s.scope_name, '公司级示例区间'), 1, @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_collection_scope s
WHERE NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_collection_sub_scope ss
          WHERE ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
      );

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(s.scope_name, '-自动采集'), LEFT(CONCAT('COMPANY-', s.id, '-AUTO'), 50), ss.id,
       'diesel', '燃料计量表示例', CONCAT(s.scope_name, '-自动采集示例'), 0, 1, 0, 'L',
       '本地示例数据', 2, 1, 1, 1, 110000 + s.id, 1, '生产用能',
       '{"source":"fixture","mode":"auto"}', @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_collection_scope s
JOIN emission_fossil_fuel_collection_sub_scope ss
  ON ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
WHERE NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_meter_info m
          WHERE m.name = CONCAT(s.scope_name, '-自动采集')
      );

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(s.scope_name, '-人工采集'), LEFT(CONCAT('COMPANY-', s.id, '-MANUAL'), 50), ss.id,
       'diesel', '燃料计量表示例', CONCAT(s.scope_name, '-人工采集示例'), 0, 0, 0, 'L',
       '本地示例数据', 2, 1, 1, 0, 110001 + s.id, 1, '生产用能', NULL,
       @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_collection_scope s
JOIN emission_fossil_fuel_collection_sub_scope ss
  ON ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
WHERE NOT EXISTS (
          SELECT 1 FROM emission_fossil_fuel_meter_info m
          WHERE m.name = CONCAT(s.scope_name, '-人工采集')
      );

INSERT INTO emission_purchased_heat_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, description, created_by, updated_by, sort_order)
SELECT CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id),
       LEFT(CONCAT('SCOPE-', s.id, '-COMPANY'), 30), s.id,
       CONCAT(s.scope_name, '公司级示例区间'), @sample_user_id, @sample_user_id, 110000 + s.id
FROM emission_purchased_heat_collection_scope s
WHERE NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_collection_sub_scope ss
          WHERE ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
      );

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(s.scope_name, '-自动采集'), LEFT(CONCAT('COMPANY-', s.id, '-AUTO'), 50), ss.id,
       'purchased-heat', '热能计量表示例', CONCAT(s.scope_name, '-自动采集示例'), 0, 1, 0, 'GJ',
       '本地示例数据', 2, 1, 1, 1, 110000 + s.id, 1, '生产用能',
       '{"source":"fixture","mode":"auto"}', @sample_user_id, @sample_user_id
FROM emission_purchased_heat_collection_scope s
JOIN emission_purchased_heat_collection_sub_scope ss
  ON ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
WHERE NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_meter_info m
          WHERE m.name = CONCAT(s.scope_name, '-自动采集')
      );

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, meter_reading_method,
     sort_order, status, energy_use, auto_meter_reading_config, created_by, updated_by)
SELECT CONCAT(s.scope_name, '-人工采集'), LEFT(CONCAT('COMPANY-', s.id, '-MANUAL'), 50), ss.id,
       'purchased-heat', '热能计量表示例', CONCAT(s.scope_name, '-人工采集示例'), 0, 0, 0, 'GJ',
       '本地示例数据', 2, 1, 1, 0, 110001 + s.id, 1, '生产用能', NULL,
       @sample_user_id, @sample_user_id
FROM emission_purchased_heat_collection_scope s
JOIN emission_purchased_heat_collection_sub_scope ss
  ON ss.sub_scope_name = CONCAT(LEFT(s.scope_name, 80), '-示例区间-', s.id)
WHERE NOT EXISTS (
          SELECT 1 FROM emission_purchased_heat_meter_info m
          WHERE m.name = CONCAT(s.scope_name, '-人工采集')
      );

INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 2, m.id, CASE WHEN m.meter_reading_method = 1 THEN 860.000000 ELSE 86.000000 END,
       DATE_SUB(NOW(), INTERVAL 2 DAY), 1, DATE_SUB(NOW(), INTERVAL 2 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_fossil_fuel_meter_info m
WHERE m.data_source_system = '本地示例数据'
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type = 2 AND r.collection_point_id = m.id);

INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status,
     last_fetch_time, collection_point_name, emission_subcategory, measurement_unit,
     meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 3, m.id, CASE WHEN m.meter_reading_method = 1 THEN 420.000000 ELSE 42.000000 END,
       DATE_SUB(NOW(), INTERVAL 3 DAY), 1, DATE_SUB(NOW(), INTERVAL 3 DAY), m.name,
       m.emission_subcategory, m.measurement_unit, m.meter_reading_method, m.is_cumulative,
       @sample_user_id, @sample_user_id
FROM emission_purchased_heat_meter_info m
WHERE m.data_source_system = '本地示例数据'
  AND NOT EXISTS (SELECT 1 FROM emission_collection_record r
                  WHERE r.collection_point_type = 3 AND r.collection_point_id = m.id);
