-- Display seed for the energy analysis page.
-- Safe to re-run. Does not update calculation tasks 11, 21, 22, or 23.
-- Numbers are for page display only.

SET NAMES utf8mb4;
USE carbon_emissions;

INSERT INTO emission_energy_category (id, category_code, category_name, parent_id, level, sort_order, status, created_by)
SELECT 9101, 'EC01', '生产用能', NULL, 1, 1, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_energy_category WHERE category_code = 'EC01');

INSERT INTO emission_energy_category (id, category_code, category_name, parent_id, level, sort_order, status, created_by)
SELECT 9104, 'EC03', '非生产综合用能', NULL, 1, 2, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_energy_category WHERE category_code = 'EC03');

INSERT INTO emission_energy_category (id, category_code, category_name, parent_id, level, sort_order, status, created_by)
SELECT 9102, 'EC0101', '牵引供电', p.id, 2, 1, 1, 1
FROM emission_energy_category p
WHERE p.category_code = 'EC01'
  AND NOT EXISTS (SELECT 1 FROM emission_energy_category WHERE category_code = 'EC0101')
LIMIT 1;

INSERT INTO emission_energy_category (id, category_code, category_name, parent_id, level, sort_order, status, created_by)
SELECT 9103, 'EC0102', '内燃机车牵引', p.id, 2, 2, 1, 1
FROM emission_energy_category p
WHERE p.category_code = 'EC01'
  AND NOT EXISTS (SELECT 1 FROM emission_energy_category WHERE category_code = 'EC0102')
LIMIT 1;

INSERT INTO emission_energy_category (id, category_code, category_name, parent_id, level, sort_order, status, created_by)
SELECT 9105, 'EC0301', '办公场所', p.id, 2, 1, 1, 1
FROM emission_energy_category p
WHERE p.category_code = 'EC03'
  AND NOT EXISTS (SELECT 1 FROM emission_energy_category WHERE category_code = 'EC0301')
LIMIT 1;

INSERT INTO emission_template (id, name, description, created_by, enabled)
SELECT 502, '能耗统计展示模板', '仅供能耗统计分析页面展示，不代表正式核算结果', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_template WHERE id = 502);

SET @analysis_root_node_id := (SELECT id FROM emission_node WHERE parent_id IS NULL ORDER BY id LIMIT 1);

INSERT INTO emission_node (name, type_id, parent_id, sort_order, created_by)
SELECT '肃宁分公司', 2, @analysis_root_node_id, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE name = '肃宁分公司' OR name LIKE '肃宁分公司-%');
INSERT INTO emission_node (name, type_id, parent_id, sort_order, created_by)
SELECT '原平分公司', 2, @analysis_root_node_id, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE name = '原平分公司');
INSERT INTO emission_node (name, type_id, parent_id, sort_order, created_by)
SELECT '黄骅港分公司', 2, @analysis_root_node_id, 3, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE name = '黄骅港分公司');

SET @analysis_suring_node_id := (
    SELECT id FROM emission_node WHERE name = '肃宁分公司' OR name LIKE '肃宁分公司-%' ORDER BY id LIMIT 1
);
SET @analysis_yuanping_node_id := (SELECT id FROM emission_node WHERE name = '原平分公司' ORDER BY id LIMIT 1);
SET @analysis_huanghuagang_node_id := (SELECT id FROM emission_node WHERE name = '黄骅港分公司' ORDER BY id LIMIT 1);

INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3111, '肃宁机务', 2, @analysis_suring_node_id, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3111);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3112, '肃宁工务', 2, @analysis_suring_node_id, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3112);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3131, '原平机务', 2, @analysis_yuanping_node_id, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3131);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3132, '原平工务', 2, @analysis_yuanping_node_id, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3132);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3151, '黄骅港机务', 2, @analysis_huanghuagang_node_id, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3151);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3152, '黄骅港工务', 2, @analysis_huanghuagang_node_id, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3152);

INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3121, '肃宁机务一站', 2, 3111, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3121);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3122, '肃宁机务二站', 2, 3111, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3122);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3123, '肃宁工务一站', 2, 3112, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3123);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3124, '肃宁工务二站', 2, 3112, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3124);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3141, '原平机务一站', 2, 3131, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3141);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3142, '原平机务二站', 2, 3131, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3142);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3143, '原平工务一站', 2, 3132, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3143);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3144, '原平工务二站', 2, 3132, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3144);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3161, '黄骅港机务一站', 2, 3151, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3161);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3162, '黄骅港机务二站', 2, 3151, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3162);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3163, '黄骅港工务一站', 2, 3152, 1, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3163);
INSERT INTO emission_node (id, name, type_id, parent_id, sort_order, created_by)
SELECT 3164, '黄骅港工务二站', 2, 3152, 2, 1
WHERE NOT EXISTS (SELECT 1 FROM emission_node WHERE id = 3164);

INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT @analysis_yuanping_node_id, 'YP', '原平', 1, 'BRANCH', '展示用组织，不代表正式核算范围'
WHERE @analysis_yuanping_node_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = @analysis_yuanping_node_id);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT @analysis_huanghuagang_node_id, 'HHG', '黄骅港', 1, 'BRANCH', '展示用组织，不代表正式核算范围'
WHERE @analysis_huanghuagang_node_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = @analysis_huanghuagang_node_id);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3111, 'SN-JW', '肃宁机务', 1, 'REGION', '展示用部门'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3111);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3112, 'SN-GW', '肃宁工务', 1, 'REGION', '展示用部门'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3112);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3131, 'YP-JW', '原平机务', 1, 'REGION', '展示用部门'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3131);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3132, 'YP-GW', '原平工务', 1, 'REGION', '展示用部门'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3132);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3151, 'HHG-JW', '黄骅港机务', 1, 'REGION', '展示用部门'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3151);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3152, 'HHG-GW', '黄骅港工务', 1, 'REGION', '展示用部门'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3152);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3121, 'SN-JW-1', '肃宁机务一站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3121);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3122, 'SN-JW-2', '肃宁机务二站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3122);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3123, 'SN-GW-1', '肃宁工务一站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3123);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3124, 'SN-GW-2', '肃宁工务二站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3124);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3141, 'YP-JW-1', '原平机务一站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3141);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3142, 'YP-JW-2', '原平机务二站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3142);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3143, 'YP-GW-1', '原平工务一站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3143);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3144, 'YP-GW-2', '原平工务二站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3144);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3161, 'HHG-JW-1', '黄骅港机务一站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3161);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3162, 'HHG-JW-2', '黄骅港机务二站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3162);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3163, 'HHG-GW-1', '黄骅港工务一站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3163);
INSERT INTO emission_node_info (node_id, node_code, short_name, include_in_calculation, node_category, unit_description)
SELECT 3164, 'HHG-GW-2', '黄骅港工务二站', 1, 'STATION', '展示用站点'
WHERE NOT EXISTS (SELECT 1 FROM emission_node_info WHERE node_id = 3164);

DROP TEMPORARY TABLE IF EXISTS tmp_display_org;
CREATE TEMPORARY TABLE tmp_display_org (
    seq INT NOT NULL PRIMARY KEY,
    node_id BIGINT NOT NULL,
    parent_seq INT NULL,
    org_name VARCHAR(200) NOT NULL,
    node_category VARCHAR(50) NOT NULL,
    scale DECIMAL(10, 4) NOT NULL
);

INSERT INTO tmp_display_org (seq, node_id, parent_seq, org_name, node_category, scale) VALUES
(1, @analysis_suring_node_id, NULL, '肃宁分公司', 'BRANCH', 1.0000),
(2, 3111, 1, '肃宁机务', 'REGION', 0.4600),
(3, 3112, 1, '肃宁工务', 'REGION', 0.3800),
(4, 3121, 2, '肃宁机务一站', 'STATION', 0.2200),
(5, 3122, 2, '肃宁机务二站', 'STATION', 0.1600),
(6, 3123, 3, '肃宁工务一站', 'STATION', 0.2000),
(7, 3124, 3, '肃宁工务二站', 'STATION', 0.1400),
(8, @analysis_yuanping_node_id, NULL, '原平分公司', 'BRANCH', 0.7200),
(9, 3131, 8, '原平机务', 'REGION', 0.3400),
(10, 3132, 8, '原平工务', 'REGION', 0.2600),
(11, 3141, 9, '原平机务一站', 'STATION', 0.1600),
(12, 3142, 9, '原平机务二站', 'STATION', 0.1200),
(13, 3143, 10, '原平工务一站', 'STATION', 0.1400),
(14, 3144, 10, '原平工务二站', 'STATION', 0.1000),
(15, @analysis_huanghuagang_node_id, NULL, '黄骅港分公司', 'BRANCH', 0.5500),
(16, 3151, 15, '黄骅港机务', 'REGION', 0.2600),
(17, 3152, 15, '黄骅港工务', 'REGION', 0.2000),
(18, 3161, 16, '黄骅港机务一站', 'STATION', 0.1200),
(19, 3162, 16, '黄骅港机务二站', 'STATION', 0.0900),
(20, 3163, 17, '黄骅港工务一站', 'STATION', 0.1100),
(21, 3164, 17, '黄骅港工务二站', 'STATION', 0.0800);

DROP TEMPORARY TABLE IF EXISTS tmp_display_month;
CREATE TEMPORARY TABLE tmp_display_month (
    template_id BIGINT NOT NULL PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    year_factor DECIMAL(10, 4) NOT NULL
);

INSERT INTO tmp_display_month (template_id, start_date, end_date, year_factor)
WITH RECURSIVE months AS (
    SELECT 0 AS n, DATE('2025-01-01') AS start_date
    UNION ALL
    SELECT n + 1, DATE_ADD(start_date, INTERVAL 1 MONTH) FROM months WHERE n < 23
)
SELECT 4101 + n, start_date, LAST_DAY(start_date), IF(YEAR(start_date) = 2026, 1.0800, 1.0000)
FROM months;

DROP TEMPORARY TABLE IF EXISTS tmp_display_variety;
CREATE TEMPORARY TABLE tmp_display_variety (
    seq INT NOT NULL PRIMARY KEY,
    subcategory VARCHAR(50) NOT NULL,
    emission_category VARCHAR(100) NOT NULL,
    unit_code VARCHAR(50) NOT NULL,
    category_l1 VARCHAR(50) NOT NULL,
    category_l2 VARCHAR(50) NOT NULL,
    carbon_factor DECIMAL(15, 6) NOT NULL,
    base_value DECIMAL(18, 6) NOT NULL,
    point_type INT NOT NULL
);

INSERT INTO tmp_display_variety (seq, subcategory, emission_category, unit_code, category_l1, category_l2, carbon_factor, base_value, point_type) VALUES
(1, 'PE_PF', '电力', 'MWh', 'EC01', 'EC0101', 0.530600, 80.000000, 1),
(2, 'FF_D', '化石燃料', 't', 'EC01', 'EC0102', 3.150000, 8.000000, 2),
(3, 'PH_HD', '热力', 'GJ', 'EC03', 'EC0301', 0.110000, 40.000000, 3);

INSERT INTO emission_calculation_template (
    id, template_id, calculation_cycle_start_date, calculation_cycle_end_date,
    calculation_start_time, calculation_end_time, status, error_code,
    task_initiator, initiator_id, initiator_name, created_by
)
SELECT m.template_id, 502, m.start_date, m.end_date,
       TIMESTAMP(m.start_date, '08:00:00'), TIMESTAMP(m.end_date, '18:00:00'), 2, 0,
       2, 1, '展示数据', 1
FROM tmp_display_month m
WHERE NOT EXISTS (SELECT 1 FROM emission_calculation_template t WHERE t.id = m.template_id);

INSERT INTO emission_calculation_node (
    id, calculation_template_id, node_id, name, type_id, parent_id, node_category,
    include_in_calculation, created_by
)
SELECT m.template_id * 100 + o.seq,
       m.template_id,
       o.node_id,
       o.org_name,
       2,
       CASE WHEN o.parent_seq IS NULL THEN NULL ELSE m.template_id * 100 + o.parent_seq END,
       o.node_category,
       b'1',
       1
FROM tmp_display_month m
JOIN tmp_display_org o
WHERE NOT EXISTS (
    SELECT 1 FROM emission_calculation_node n WHERE n.id = m.template_id * 100 + o.seq
);

INSERT INTO emission_collection_node_data (
    id, calculation_node_id, collection_point_type, emission_category, emission_subcategory,
    carbon_emission_factor, measurement_unit, energy_category_l1, energy_category_l2,
    energy_measurement_value, carbon_emission, adjusted_energy_value, adjusted_carbon_emission,
    data_status, collection_record_start_date, collection_record_end_date, created_by
)
SELECT src.id,
       src.calc_node_id,
       src.point_type,
       src.emission_category,
       src.subcategory,
       src.carbon_factor,
       src.unit_code,
       src.category_l1,
       src.category_l2,
       src.energy_value,
       ROUND(src.energy_value * src.carbon_factor, 3),
       src.energy_value,
       ROUND(src.energy_value * src.carbon_factor, 3),
       1,
       src.start_date,
       src.end_date,
       1
FROM (
    SELECT (m.template_id * 100 + o.seq) * 10 + v.seq AS id,
           m.template_id * 100 + o.seq AS calc_node_id,
           v.point_type,
           v.emission_category,
           v.subcategory,
           v.carbon_factor,
           v.unit_code,
           v.category_l1,
           v.category_l2,
           ROUND(o.scale * (0.90 + 0.02 * MONTH(m.start_date)) * m.year_factor * v.base_value, 3) AS energy_value,
           m.start_date,
           m.end_date
    FROM tmp_display_month m
    JOIN tmp_display_org o
    JOIN tmp_display_variety v
    WHERE NOT (o.node_id = 1001 AND m.start_date IN ('2025-02-01', '2025-03-01'))
) src
WHERE NOT EXISTS (SELECT 1 FROM emission_collection_node_data d WHERE d.id = src.id);

DROP TEMPORARY TABLE IF EXISTS tmp_display_org;
DROP TEMPORARY TABLE IF EXISTS tmp_display_month;
DROP TEMPORARY TABLE IF EXISTS tmp_display_variety;
