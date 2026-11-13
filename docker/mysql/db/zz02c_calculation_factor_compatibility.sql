-- Ensure the statistics/demo calculation template has every factor used by its
-- collection points.  The statements are idempotent and resolve IDs by name,
-- so they work after a fresh schema import and on existing databases.
SET NAMES utf8mb4;
USE carbon_emissions;

SET @fixture_user_id := COALESCE((SELECT user_id FROM sys_user WHERE user_name = 'admin' LIMIT 1), 1);
SET @statistics_template_id := (
    SELECT id FROM emission_template
    WHERE name = '统计查询与GoView演示模板'
    ORDER BY id DESC LIMIT 1
);
SET @statistics_factor_template_id := (
    SELECT factor_template_id FROM emission_template
    WHERE id = @statistics_template_id AND factor_template_id IS NOT NULL
    LIMIT 1
);
SET @statistics_factor_template_id := COALESCE(
    @statistics_factor_template_id,
    (SELECT id FROM emission_factor_template
     WHERE template_name = '联调示例-肃宁分公司因子模板'
     ORDER BY id DESC LIMIT 1)
);

-- A template without a factor set cannot calculate any collection node.  The
-- normal statistics seed creates this row; this fallback keeps older installs
-- repairable without changing the user's selected template.
INSERT INTO emission_factor_template
    (template_name, template_description, is_shared, status, created_by, updated_by)
SELECT '联调示例-肃宁分公司因子模板',
       '用于统计查询与核算流程的电力、柴油、热力示例因子。',
       1, 1, @fixture_user_id, @fixture_user_id
WHERE @statistics_factor_template_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM emission_factor_template
      WHERE template_name = '联调示例-肃宁分公司因子模板'
  );

SET @statistics_factor_template_id := COALESCE(
    @statistics_factor_template_id,
    (SELECT id FROM emission_factor_template
     WHERE template_name = '联调示例-肃宁分公司因子模板'
     ORDER BY id DESC LIMIT 1)
);

UPDATE emission_template
SET factor_template_id = @statistics_factor_template_id,
    updated_at = NOW()
WHERE id = @statistics_template_id
  AND @statistics_template_id IS NOT NULL
  AND @statistics_factor_template_id IS NOT NULL
  AND (factor_template_id IS NULL OR factor_template_id <> @statistics_factor_template_id);

-- Keep the existing electricity snapshot and add the two other categories used
-- by the demo tree.  ON DUPLICATE KEY UPDATE also repairs an incomplete row.
INSERT INTO emission_default_factor
    (template_id, subcategory_code, subcategory_name, factor_source, factor_id,
     factor_name, factor_value, factor_unit, factor_description, status,
     created_by, updated_by)
SELECT @statistics_factor_template_id, 'FF_D', '柴油', 'FOSSIL', f.id,
       f.emission_factor_name, f.emission_factor, f.factor_unit, f.description,
       1, @fixture_user_id, @fixture_user_id
FROM emission_fossil_fuel_emission_factor f
WHERE @statistics_factor_template_id IS NOT NULL
  AND f.fuel_type = '柴油'
ON DUPLICATE KEY UPDATE
    subcategory_name = VALUES(subcategory_name), factor_source = VALUES(factor_source),
    factor_id = VALUES(factor_id), factor_name = VALUES(factor_name),
    factor_value = VALUES(factor_value), factor_unit = VALUES(factor_unit),
    factor_description = VALUES(factor_description), status = 1,
    updated_by = VALUES(updated_by), updated_at = NOW();

INSERT INTO emission_default_factor
    (template_id, subcategory_code, subcategory_name, factor_source, factor_id,
     factor_name, factor_value, factor_unit, factor_description, status,
     created_by, updated_by)
SELECT @statistics_factor_template_id, 'PH_HD', '热力数据', 'THERMAL', t.id,
       t.emission_factor_name, t.emission_factor, TRIM(t.unit), t.description,
       1, @fixture_user_id, @fixture_user_id
FROM emission_thermal_emission_factor t
WHERE @statistics_factor_template_id IS NOT NULL
  AND t.emission_factor_name = '全国统一热力排放因子缺省值'
ON DUPLICATE KEY UPDATE
    subcategory_name = VALUES(subcategory_name), factor_source = VALUES(factor_source),
    factor_id = VALUES(factor_id), factor_name = VALUES(factor_name),
    factor_value = VALUES(factor_value), factor_unit = VALUES(factor_unit),
    factor_description = VALUES(factor_description), status = 1,
    updated_by = VALUES(updated_by), updated_at = NOW();

