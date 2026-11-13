-- 004_fix_non_jlg_traction.sql
-- 业务口径修正：牵引电力仅属于机辆分公司（JLG）。
-- 肃宁（SNF）、原平（YPF）没有牵引电力，电力总和全部为辅助生产电力。
-- 本脚本可重复执行，只处理 SNF/YPF，不影响 JLG 的牵引/辅助拆分。
USE `carbon_emissions`;

-- 1) 删除 SNF/YPF 错误的牵引电力推算记录
DELETE FROM `prediction_activity_monthly`
WHERE `org_id` IN ('SNF', 'YPF')
  AND `var_id` = 'ELEC_TRAC';

-- 2) 肃宁/原平辅助生产电力 = 电力总和
UPDATE `prediction_activity_monthly` a
JOIN `prediction_activity_monthly` t
  ON t.`org_id` = a.`org_id`
 AND t.`period` = a.`period`
 AND t.`var_id` = 'ELEC_TOTAL'
SET a.`value` = t.`value`,
    a.`reported_value` = t.`reported_value`,
    a.`source_status` = '原始',
    a.`is_estimated` = 0
WHERE a.`org_id` IN ('SNF', 'YPF')
  AND a.`var_id` = 'ELEC_AUX';

-- 3) 校验：以下查询应返回 0 行
-- SELECT org_id, period, var_id
-- FROM prediction_activity_monthly
-- WHERE org_id IN ('SNF','YPF') AND var_id IN ('ELEC_TRAC','TURNOVER');
