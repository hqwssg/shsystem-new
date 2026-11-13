USE `carbon_emissions`;

-- 组织（platform_dept_id 与平台 sys_dept 对齐）
INSERT INTO `prediction_org`
(`org_id`,`org_name`,`org_level`,`parent_org_id`,`platform_dept_id`,`province`,`heating_months`,`latitude`,`longitude`,`status`)
VALUES
('SHL','国能朔黄铁路发展有限责任公司',1,NULL,3000,'河北/山西',NULL,38.4300,115.8300,'active'),
('JLG','机辆分公司',2,'SHL',3030,'河北/山西','1,2,3,4,11,12',38.4300,115.8300,'active'),
('SNF','肃宁分公司',2,'SHL',3020,'河北','1,2,3,11,12',38.4300,115.8300,'active'),
('YPF','原平分公司',2,'SHL',3010,'山西','1,2,3,4,11,12',38.7300,112.7100,'active')
ON DUPLICATE KEY UPDATE
  `org_name`=VALUES(`org_name`),`platform_dept_id`=VALUES(`platform_dept_id`),
  `province`=VALUES(`province`),`heating_months`=VALUES(`heating_months`);

-- 能源/活动品种
INSERT INTO `prediction_energy_var`
(`var_id`,`var_name`,`unit`,`var_category`,`is_traction`,`is_target`,`sort_order`,`remark`)
VALUES
('TURNOVER','货运周转量','百万吨公里','operation',0,0,10,'机辆分公司口径；2019-2020为推算'),
('GAS','天然气','万立方米','fuel',0,0,20,''),
('GASOLINE','汽油','吨','fuel',0,0,30,''),
('DIESEL','柴油','吨','fuel',0,0,40,'内燃机车用油'),
('ELEC_TOTAL','电力总和','MWh','electricity',0,0,50,'牵引用电+辅助生产用电'),
('ELEC_TRAC','牵引电力','MWh','electricity',1,0,60,'2019-2023为按辅占比推算'),
('ELEC_AUX','辅助生产电力','MWh','electricity',0,0,70,''),
('HEAT','热力（可比口径）','GJ','heat',0,0,80,'按0.9224 GJ/m2基准系数还原'),
('HEAT_REPORTED','热力（报表口径）','GJ','heat',0,0,90,'2025年按新折算系数填报'),
('DIESEL_LOCO_COUNT','内燃机车运用台数','台','operation',0,0,100,'2024下半年起逐步减量，用于情景输入'),
('CO2_COMPARABLE','碳排放（可比口径）','tCO2e','target',0,1,200,'固定2025年电力因子与基准热力系数，用于建模'),
('CO2_REPORTED','碳排放（报表口径）','tCO2e','target',0,1,210,'按当年实际因子与热力口径')
ON DUPLICATE KEY UPDATE
  `var_name`=VALUES(`var_name`),`unit`=VALUES(`unit`),`var_category`=VALUES(`var_category`),
  `is_traction`=VALUES(`is_traction`),`is_target`=VALUES(`is_target`),`remark`=VALUES(`remark`);

-- 排放因子（按年切片）
INSERT INTO `prediction_emission_factor`
(`var_id`,`factor_value`,`factor_unit`,`factor_version`,`effective_from`,`effective_to`,`factor_source`,`is_caliber_change`,`policy_basis`)
VALUES
('GAS',21.621732,'tCO2/万m3','EF-GAS-2019','2019-01-01',NULL,'企业核算因子',0,'原始台账采用值'),
('GASOLINE',3.042475,'tCO2/t','EF-GASOLINE-2019','2019-01-01',NULL,'企业核算因子',0,'原始台账采用值'),
('DIESEL',3.145245,'tCO2/t','EF-DIESEL-2019','2019-01-01',NULL,'企业核算因子',0,'原始台账采用值'),
('HEAT',0.110000,'tCO2/GJ','EF-HEAT-2019','2019-01-01',NULL,'企业核算因子',0,'原始台账采用值'),
('ELEC_TOTAL',0.884300,'tCO2/MWh','EF-ELEC-2019','2019-01-01','2021-12-31','华北区域电网/企业核算因子',1,'2019-2021年台账采用值'),
('ELEC_TOTAL',0.570300,'tCO2/MWh','EF-ELEC-2022','2022-01-01','2022-12-31','全国电网平均因子',1,'2022年台账采用值'),
('ELEC_TOTAL',0.556800,'tCO2/MWh','EF-ELEC-2023','2023-01-01','2023-12-31','全国电网平均因子',1,'2023年台账采用值'),
('ELEC_TOTAL',0.536600,'tCO2/MWh','EF-ELEC-2024','2024-01-01','2024-12-31','全国电网平均因子',1,'2024年台账采用值'),
('ELEC_TOTAL',0.530600,'tCO2/MWh','EF-ELEC-2025','2025-01-01',NULL,'全国电网平均因子',0,'2025年台账采用值；作为可比口径基准因子')
ON DUPLICATE KEY UPDATE
  `factor_value`=VALUES(`factor_value`),`factor_unit`=VALUES(`factor_unit`),
  `factor_version`=VALUES(`factor_version`),`effective_to`=VALUES(`effective_to`),
  `factor_source`=VALUES(`factor_source`),
  `is_caliber_change`=VALUES(`is_caliber_change`),`policy_basis`=VALUES(`policy_basis`);

-- 供热面积折算系数与电网因子口径规则
INSERT INTO `prediction_caliber_rule`
(`rule_id`,`org_id`,`rule_type`,`effective_from`,`effective_to`,`rule_value`,`unit`,`rule_version`,`source`,`note`)
VALUES
('JLG-HEAT-2019','JLG','heat_area_factor','2019-01-01',NULL,0.9224,'GJ/m2','CAL-JLG-2019','企业供热协议','机辆分公司四站点按面积收费'),
('SNF-HEAT-2019','SNF','heat_area_factor','2019-01-01','2024-12-31',0.9224,'GJ/m2','CAL-SNF-2019','企业供热协议','行唐/黄骅港港前/港口站按面积折算'),
('SNF-HEAT-2025','SNF','heat_area_factor','2025-01-01',NULL,0.3800,'GJ/m2','CAL-SNF-2025','企业供热协议','2025年核算系数调整，面积未变'),
('YPF-HEAT-2019','YPF','heat_area_factor','2019-01-01','2024-12-31',0.9224,'GJ/m2','CAL-YPF-2019','企业供热协议','原平分公司全部按面积折算'),
('YPF-HEAT-2025','YPF','heat_area_factor','2025-01-01',NULL,0.3340,'GJ/m2','CAL-YPF-2025','企业供热协议','2025年核算系数调整，面积未变'),
('GRID-2019','ALL','grid_factor','2019-01-01','2021-12-31',0.8843,'tCO2/MWh','CAL-GRID-2019','企业核算因子',''),
('GRID-2022','ALL','grid_factor','2022-01-01','2022-12-31',0.5703,'tCO2/MWh','CAL-GRID-2022','企业核算因子',''),
('GRID-2023','ALL','grid_factor','2023-01-01','2023-12-31',0.5568,'tCO2/MWh','CAL-GRID-2023','企业核算因子',''),
('GRID-2024','ALL','grid_factor','2024-01-01','2024-12-31',0.5366,'tCO2/MWh','CAL-GRID-2024','企业核算因子',''),
('GRID-2025','ALL','grid_factor','2025-01-01',NULL,0.5306,'tCO2/MWh','CAL-GRID-2025','企业核算因子','可比口径基准')
ON DUPLICATE KEY UPDATE
  `rule_value`=VALUES(`rule_value`),`effective_to`=VALUES(`effective_to`),
  `rule_version`=VALUES(`rule_version`),
  `source`=VALUES(`source`),`note`=VALUES(`note`);

-- 情景定义
INSERT INTO `prediction_scenario`
(`scenario_id`,`scenario_name`,`description`,`config`,`is_default`)
VALUES
('BAU','基准情景','政策与外部因子按最近趋势外推，活动量按历史规律延续',
 JSON_OBJECT('coal_price_multiplier',1.0,'activity_multiplier',1.0,'grid_factor',0.5306),1),
('COAL_HIGH','煤价上行情景','动力煤长协价较基准+10%，其余不变（仅作敏感性参考）',
 JSON_OBJECT('coal_price_multiplier',1.10,'activity_multiplier',1.0,'grid_factor',0.5306),0),
('COAL_LOW','煤价下行情景','动力煤长协价较基准-10%，其余不变（仅作敏感性参考）',
 JSON_OBJECT('coal_price_multiplier',0.90,'activity_multiplier',1.0,'grid_factor',0.5306),0),
('EFFICIENCY','能效提升情景','活动量较基准-3%，其余不变',
 JSON_OBJECT('coal_price_multiplier',1.0,'activity_multiplier',0.97,'grid_factor',0.5306),0)
ON DUPLICATE KEY UPDATE
  `scenario_name`=VALUES(`scenario_name`),`description`=VALUES(`description`),
  `config`=VALUES(`config`),`is_default`=VALUES(`is_default`);

-- 政策事件时间线（定性政策结构化记录，不进入GRA）
INSERT INTO `prediction_policy_event`
(`event_id`,`event_name`,`start_period`,`end_period`,`dimension`,`description`,`source_url`,`intensity`)
VALUES
('EVT-2021-COAL','煤价过快上涨调控与保供稳价','2021-10-01','2022-06-30','price',
 '国家发展改革委等部门对动力煤价格过快上涨采取保供稳价、查处囤积居奇等措施，秦皇岛港5500大卡煤价由高位回落。',
 'https://zfxxgk.ndrc.gov.cn/wap/iteminfo.jsp?id=18700',0.80),
('EVT-2022-303','动力煤中长期交易价格合理区间','2022-02-01',NULL,'price',
 '发改价格〔2022〕303号明确秦皇岛港下水煤（5500千卡）中长期交易价格合理区间为570—770元/吨（含税）。',
 'https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=92934',0.90),
('EVT-2024-ETS','全国碳市场扩容','2024-05-01',NULL,'carbon_market',
 '全国碳市场由发电行业向钢铁、水泥、铝冶炼等行业扩容，碳价信号增强；铁路运输尚未纳入履约范围。',
 'https://www.mee.gov.cn/',0.45),
('EVT-2025-GRID','电网平均排放因子更新','2025-01-01',NULL,'grid',
 '2025年企业核算采用0.5306 tCO2/MWh电网平均因子，较2024年0.5366小幅下降，较2019-2021年0.8843显著下降。',
 'https://www.mee.gov.cn/',0.35),
('EVT-2025-RAIL','铁路绿色低碳转型政策','2025-01-01',NULL,'transport',
 '铁路领域推进电气化、机车新能源替代与运输结构调整；机辆分公司内燃机车由2024年下半年起逐步减量。',
 'https://www.nra.gov.cn/',0.40)
ON DUPLICATE KEY UPDATE
  `event_name`=VALUES(`event_name`),`start_period`=VALUES(`start_period`),
  `end_period`=VALUES(`end_period`),`description`=VALUES(`description`),
  `source_url`=VALUES(`source_url`),`intensity`=VALUES(`intensity`);
