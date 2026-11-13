-- 化石燃料因子按所选计量单位保存时所需的正式因子量纲。
-- 通过小类、分子和分母判断已有记录，脚本可重复执行。
-- 化石燃料因子允许按所选计量单位保存；补齐相应因子量纲（重复执行安全）
INSERT INTO emission_factor_unit
    (factor_unit_code, factor_unit_name, numerator_ghg_code,
     denominator_unit_code, subcategory_code, sort_order, status)
SELECT
    CONCAT('tCO2_per_', u.unit_code, '_', i.item_code),
    CASE u.unit_code
        WHEN 't' THEN 'tCO₂/t'
        WHEN 'kg' THEN 'tCO₂/kg'
        WHEN 'g' THEN 'tCO₂/g'
        WHEN 'L' THEN 'tCO₂/L'
        WHEN 'm3' THEN 'tCO₂/m³'
        WHEN 'wan_m3' THEN 'tCO₂/万m³'
        WHEN 'Nm3' THEN 'tCO₂/Nm³'
        WHEN 'wan_Nm3' THEN 'tCO₂/万Nm³'
    END,
    'tCO2',
    u.unit_code,
    i.item_code,
    FIELD(u.unit_code, 't', 'kg', 'g', 'L', 'm3', 'wan_m3', 'Nm3', 'wan_Nm3'),
    1
FROM emission_data_dict_item i
JOIN emission_data_dict d ON d.id = i.dict_id AND d.dict_code = 'emission_subcategory'
JOIN emission_unit_standard u ON (
       (i.item_code IN ('FF_B', 'FF_LB', 'FF_CK', 'FF_PC')
            AND u.unit_code IN ('t', 'kg', 'g'))
    OR (i.item_code IN ('FF_G', 'FF_D', 'FF_C', 'FF_F', 'FF_LNG', 'FF_LPG')
            AND u.unit_code IN ('t', 'kg', 'g', 'L'))
    OR (i.item_code IN ('FF_NG', 'FF_BFG', 'FF_COG', 'FF_COK')
            AND u.unit_code IN ('m3', 'wan_m3', 'Nm3', 'wan_Nm3'))
)
LEFT JOIN emission_factor_unit existing
       ON existing.subcategory_code = i.item_code
      AND existing.numerator_ghg_code = 'tCO2'
      AND existing.denominator_unit_code = u.unit_code
WHERE i.status = 1
  AND existing.id IS NULL;

