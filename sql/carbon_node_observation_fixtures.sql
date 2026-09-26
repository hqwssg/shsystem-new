-- Repeatable local/demo fixtures for the three collection domains and model tree.
-- Names use a DEMO- prefix so the rows are easy to identify and remove.
SET NAMES utf8mb4;

SET @demo_user_id := COALESCE((SELECT user_id FROM sys_user WHERE user_name = 'admin' LIMIT 1), 1);
SET @demo_dept_id := COALESCE((SELECT dept_id FROM sys_user WHERE user_name = 'admin' LIMIT 1), 3000);

-- Electricity: station -> concentrator -> automatic/manual meters.
INSERT INTO emission_station_interval
    (name, pinyin_code, description, sort_order, status, created_by, updated_by)
SELECT 'DEMO-Suning-DingzhouWest-Station', 'DEMO-SN-DZW',
       'Demo station for model and collection observation', 900, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_station_interval WHERE name = 'DEMO-Suning-DingzhouWest-Station');
SET @demo_station_id := (SELECT id FROM emission_station_interval WHERE name = 'DEMO-Suning-DingzhouWest-Station' LIMIT 1);

INSERT INTO emission_concentrator
    (name, pinyin_code, station_interval_id, concentrator_address, description, sort_order, status, created_by, updated_by)
SELECT 'DEMO-DingzhouWest-Concentrator', 'DEMO-SN-DZW-C1', @demo_station_id, 'DEMO-C1',
       'Demo electricity concentrator', 900, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_concentrator WHERE name = 'DEMO-DingzhouWest-Concentrator');
SET @demo_concentrator_id := (SELECT id FROM emission_concentrator WHERE name = 'DEMO-DingzhouWest-Concentrator' LIMIT 1);

INSERT INTO emission_meter_info
    (name, pinyin_code, point_id, meter_address, meter_type, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, emission_subcategory,
     meter_reading_method, sort_order, status, created_by, updated_by)
SELECT 'DEMO-DingzhouWest-AutoMeter', 'DEMO-SN-DZW-MA', @demo_concentrator_id, 'DEMO-MA',
       'electricity', 'DEMO-AUTO', 'Automatic collection demo', 0, 1, 0, 'kWh', 'DEMO',
       2, 1, 1, 'purchased-electricity', 1, 1, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_meter_info WHERE name = 'DEMO-DingzhouWest-AutoMeter');
SET @demo_electric_auto_id := (SELECT id FROM emission_meter_info WHERE name = 'DEMO-DingzhouWest-AutoMeter' LIMIT 1);

INSERT INTO emission_meter_info
    (name, pinyin_code, point_id, meter_address, meter_type, meter_model, purpose_description,
     parent_meter_id, is_cumulative, is_mobile_source, measurement_unit, data_source_system,
     billing_cycle_unit, billing_cycle_start_date, billing_cycle_length, emission_subcategory,
     meter_reading_method, sort_order, status, created_by, updated_by)
SELECT 'DEMO-DingzhouWest-ManualMeter', 'DEMO-SN-DZW-MM', @demo_concentrator_id, 'DEMO-MM',
       'electricity', 'DEMO-MANUAL', 'Manual collection demo', 0, 0, 0, 'kWh', 'DEMO',
       2, 1, 1, 'purchased-electricity', 0, 2, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_meter_info WHERE name = 'DEMO-DingzhouWest-ManualMeter');
SET @demo_electric_manual_id := (SELECT id FROM emission_meter_info WHERE name = 'DEMO-DingzhouWest-ManualMeter' LIMIT 1);

-- Fossil fuel: company scope -> three business sub-scopes -> meters.
INSERT INTO emission_fossil_fuel_collection_scope
    (scope_name, pinyin_code, sort_order, description, status, created_by, updated_by)
SELECT 'DEMO-Suning-Fossil', 'DEMO-SN-FOSSIL', 900, 'Demo fossil fuel company scope', 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_collection_scope WHERE scope_name = 'DEMO-Suning-Fossil');
SET @demo_fossil_scope_id := (SELECT id FROM emission_fossil_fuel_collection_scope WHERE scope_name = 'DEMO-Suning-Fossil' LIMIT 1);

INSERT INTO emission_fossil_fuel_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, sort_order, description, status, created_by, updated_by)
SELECT x.sub_scope_name, x.pinyin_code, @demo_fossil_scope_id, x.sort_order, x.description, 1, @demo_user_id, @demo_user_id
FROM (SELECT 'DEMO-Automobile-Gasoline' sub_scope_name, 'DEMO-F-GAS' pinyin_code, 1 sort_order, 'Vehicle gasoline' description
      UNION ALL SELECT 'DEMO-Automobile-Diesel', 'DEMO-F-DIESEL', 2, 'Vehicle diesel'
      UNION ALL SELECT 'DEMO-Rail-Diesel', 'DEMO-F-RAIL', 3, 'Rail vehicle diesel') x
WHERE NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_collection_sub_scope s WHERE s.sub_scope_name = x.sub_scope_name);
SET @demo_fossil_sub_id := (SELECT id FROM emission_fossil_fuel_collection_sub_scope WHERE sub_scope_name = 'DEMO-Rail-Diesel' LIMIT 1);

INSERT INTO emission_fossil_fuel_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, purpose_description, parent_meter_id,
     is_cumulative, is_mobile_source, measurement_unit, data_source_system, billing_cycle_unit,
     billing_cycle_start_date, billing_cycle_length, meter_reading_method, sort_order, status, created_by, updated_by)
SELECT 'DEMO-Rail-Diesel-Meter', 'DEMO-F-RAIL-M1', @demo_fossil_sub_id, 'diesel', 'Rail vehicle diesel demo',
       0, 0, 1, 'L', 'DEMO', 2, 1, 1, 0, 1, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_fossil_fuel_meter_info WHERE name = 'DEMO-Rail-Diesel-Meter');
SET @demo_fossil_meter_id := (SELECT id FROM emission_fossil_fuel_meter_info WHERE name = 'DEMO-Rail-Diesel-Meter' LIMIT 1);

-- Purchased heat: company scope -> heating areas -> meter.
INSERT INTO emission_purchased_heat_collection_scope
    (scope_name, pinyin_code, sort_order, description, created_by, updated_by)
SELECT 'DEMO-Suning-Heat', 'DEMO-SN-HEAT', 900, 'Demo purchased heat company scope', @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_purchased_heat_collection_scope WHERE scope_name = 'DEMO-Suning-Heat');
SET @demo_heat_scope_id := (SELECT id FROM emission_purchased_heat_collection_scope WHERE scope_name = 'DEMO-Suning-Heat' LIMIT 1);

INSERT INTO emission_purchased_heat_collection_sub_scope
    (sub_scope_name, pinyin_code, collection_scope_id, description, created_by, updated_by)
SELECT x.sub_scope_name, x.pinyin_code, @demo_heat_scope_id, x.description, @demo_user_id, @demo_user_id
FROM (SELECT 'DEMO-Suning-Office-Heating' sub_scope_name, 'DEMO-H-OFFICE' pinyin_code, 'Office heating' description
      UNION ALL SELECT 'DEMO-Suning-Workshop-Heating', 'DEMO-H-WORKSHOP', 'Workshop heating') x
WHERE NOT EXISTS (SELECT 1 FROM emission_purchased_heat_collection_sub_scope s WHERE s.sub_scope_name = x.sub_scope_name);
SET @demo_heat_sub_id := (SELECT id FROM emission_purchased_heat_collection_sub_scope WHERE sub_scope_name = 'DEMO-Suning-Workshop-Heating' LIMIT 1);

INSERT INTO emission_purchased_heat_meter_info
    (name, pinyin_code, sub_scope_id, emission_subcategory, purpose_description, parent_meter_id,
     is_cumulative, is_mobile_source, measurement_unit, data_source_system, billing_cycle_unit,
     billing_cycle_start_date, billing_cycle_length, meter_reading_method, sort_order, status, created_by, updated_by)
SELECT 'DEMO-Suning-Workshop-HeatMeter', 'DEMO-H-WORKSHOP-M1', @demo_heat_sub_id, 'purchased-heat',
       'Workshop heat demo', 0, 1, 0, 'GJ', 'DEMO', 2, 1, 1, 1, 1, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_purchased_heat_meter_info WHERE name = 'DEMO-Suning-Workshop-HeatMeter');
SET @demo_heat_meter_id := (SELECT id FROM emission_purchased_heat_meter_info WHERE name = 'DEMO-Suning-Workshop-HeatMeter' LIMIT 1);

-- Model tree: one calculation template containing electricity, fossil and heat collection nodes.
INSERT INTO emission_template (name, description, created_by, updated_by, version, enabled, template_type, task_config, check_result)
SELECT 'DEMO-Suning-Three-Domain-Model', 'Demo model covering electricity, fossil fuel and purchased heat',
       @demo_user_id, @demo_user_id, 1, 1, 2,
       '{"cycleType":"MONTHLY","executionTime":"02:00","startDate":"2026-01-01","endDate":"2099-12-31"}', 1
WHERE NOT EXISTS (SELECT 1 FROM emission_template WHERE name = 'DEMO-Suning-Three-Domain-Model');
SET @demo_template_id := (SELECT id FROM emission_template WHERE name = 'DEMO-Suning-Three-Domain-Model' LIMIT 1);

INSERT INTO emission_node (name, type_id, parent_id, template_id, source_node_id, sort_order, created_by, updated_by)
SELECT 'DEMO-Suning-Calculation', 1, NULL, @demo_template_id, 0, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE template_id = @demo_template_id AND name = 'DEMO-Suning-Calculation');
SET @demo_root_node_id := (SELECT id FROM emission_node WHERE template_id = @demo_template_id AND name = 'DEMO-Suning-Calculation' LIMIT 1);

INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description, created_by, updated_by)
SELECT @demo_root_node_id, 'DEMO-SN', 'DEMO-Suning', 1, 'COMPANY', 'Demo company boundary', @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = @demo_root_node_id);

INSERT INTO emission_node (name, type_id, parent_id, template_id, source_node_id, sort_order, created_by, updated_by)
SELECT x.node_name, 3, @demo_root_node_id, @demo_template_id, 0, x.sort_order, @demo_user_id, @demo_user_id
FROM (SELECT 'DEMO-Electricity-Collection' node_name, 1 sort_order UNION ALL
      SELECT 'DEMO-Fossil-Collection', 2 UNION ALL SELECT 'DEMO-Heat-Collection', 3) x
WHERE NOT EXISTS (SELECT 1 FROM emission_node n WHERE n.template_id = @demo_template_id AND n.name = x.node_name);

SET @demo_e_node := (SELECT id FROM emission_node WHERE template_id=@demo_template_id AND name='DEMO-Electricity-Collection' LIMIT 1);
SET @demo_f_node := (SELECT id FROM emission_node WHERE template_id=@demo_template_id AND name='DEMO-Fossil-Collection' LIMIT 1);
SET @demo_h_node := (SELECT id FROM emission_node WHERE template_id=@demo_template_id AND name='DEMO-Heat-Collection' LIMIT 1);

INSERT INTO emission_node_config (node_id, emission_category, emission_subcategory, collection_description, equipment_code, collection_point_type, collection_point_id, collection_point_status, created_by, updated_by)
SELECT @demo_e_node, 'electricity', 'purchased-electricity', 'Demo electricity collection', 'DEMO-E-001', 1, @demo_electric_auto_id, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node_config WHERE node_id=@demo_e_node);
INSERT INTO emission_node_config (node_id, emission_category, emission_subcategory, collection_description, equipment_code, collection_point_type, collection_point_id, collection_point_status, created_by, updated_by)
SELECT @demo_f_node, 'fossil-fuel', 'diesel', 'Demo fossil fuel collection', 'DEMO-F-001', 2, @demo_fossil_meter_id, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node_config WHERE node_id=@demo_f_node);
INSERT INTO emission_node_config (node_id, emission_category, emission_subcategory, collection_description, equipment_code, collection_point_type, collection_point_id, collection_point_status, created_by, updated_by)
SELECT @demo_h_node, 'purchased-heat', 'purchased-heat', 'Demo purchased heat collection', 'DEMO-H-001', 3, @demo_heat_meter_id, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_node_config WHERE node_id=@demo_h_node);

-- Seed one success and one failure so the status columns can be observed immediately.
INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status, last_fetch_time,
     collection_point_name, emission_subcategory, measurement_unit, meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 1, @demo_electric_auto_id, 1200.000000, NOW(), 1, NOW(), 'DEMO-DingzhouWest-AutoMeter', 'purchased-electricity', 'kWh', 1, 1, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_collection_record WHERE collection_point_type=1 AND collection_point_id=@demo_electric_auto_id AND collection_status=1);
INSERT INTO emission_collection_record
    (collection_point_type, collection_point_id, reading_value, collection_time, collection_status, last_fetch_time,
     collection_point_name, emission_subcategory, measurement_unit, meter_reading_method, is_cumulative, created_by, updated_by)
SELECT 2, @demo_fossil_meter_id, NULL, NOW(), 2, NOW(), 'DEMO-Rail-Diesel-Meter', 'diesel', 'L', 1, 0, @demo_user_id, @demo_user_id
WHERE NOT EXISTS (SELECT 1 FROM emission_collection_record WHERE collection_point_type=2 AND collection_point_id=@demo_fossil_meter_id AND collection_status=2);

UPDATE emission_meter_info SET last_collection_status=1, last_collection_message='DEMO_SUCCESS', last_collection_time=NOW() WHERE id=@demo_electric_auto_id;
UPDATE emission_fossil_fuel_meter_info SET last_collection_status=2, last_collection_message='DEMO_FAILURE' WHERE id=@demo_fossil_meter_id;
UPDATE emission_purchased_heat_meter_info SET last_collection_status=NULL, last_collection_message=NULL WHERE id=@demo_heat_meter_id;
UPDATE emission_node_config SET last_collection_status=1, last_collection_message='DEMO_SUCCESS', last_collection_time=NOW() WHERE node_id=@demo_e_node;
UPDATE emission_node_config SET last_collection_status=2, last_collection_message='DEMO_FAILURE', last_collection_time=NULL WHERE node_id=@demo_f_node;
UPDATE emission_node_config SET last_collection_status=NULL, last_collection_message=NULL, last_collection_time=NULL WHERE node_id=@demo_h_node;

-- Company-level grants for the demo roots; existing scope permission tables remain authoritative.
INSERT IGNORE INTO sys_carbon_company (dept_id, created_by, updated_by)
SELECT @demo_dept_id, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_dept WHERE dept_id=@demo_dept_id);
INSERT IGNORE INTO sys_carbon_scope_owner (scope_type, scope_id, company_dept_id, created_by, updated_by)
SELECT 'electricity', @demo_station_id, @demo_dept_id, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_company WHERE dept_id=@demo_dept_id);
INSERT IGNORE INTO sys_carbon_scope_owner (scope_type, scope_id, company_dept_id, created_by, updated_by)
SELECT 'fossil', @demo_fossil_scope_id, @demo_dept_id, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_company WHERE dept_id=@demo_dept_id);
INSERT IGNORE INTO sys_carbon_scope_owner (scope_type, scope_id, company_dept_id, created_by, updated_by)
SELECT 'heat', @demo_heat_scope_id, @demo_dept_id, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_company WHERE dept_id=@demo_dept_id);

INSERT IGNORE INTO sys_carbon_scope_grant
    (scope_type, scope_id, dept_id, node_type, node_id, can_read, can_write, can_delegate, created_by, updated_by)
SELECT 'electricity', @demo_station_id, @demo_dept_id, 'station', @demo_station_id, 1, 1, 1, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_scope_owner WHERE scope_type='electricity' AND scope_id=@demo_station_id);
INSERT IGNORE INTO sys_carbon_scope_grant
    (scope_type, scope_id, dept_id, node_type, node_id, can_read, can_write, can_delegate, created_by, updated_by)
SELECT 'fossil', @demo_fossil_scope_id, @demo_dept_id, 'scope', @demo_fossil_scope_id, 1, 1, 1, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_scope_owner WHERE scope_type='fossil' AND scope_id=@demo_fossil_scope_id);
INSERT IGNORE INTO sys_carbon_scope_grant
    (scope_type, scope_id, dept_id, node_type, node_id, can_read, can_write, can_delegate, created_by, updated_by)
SELECT 'heat', @demo_heat_scope_id, @demo_dept_id, 'scope', @demo_heat_scope_id, 1, 1, 1, @demo_user_id, @demo_user_id
WHERE EXISTS (SELECT 1 FROM sys_carbon_scope_owner WHERE scope_type='heat' AND scope_id=@demo_heat_scope_id);
