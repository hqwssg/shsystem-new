-- 仅用于本地专用演示模板；没有更新或删除语句。
-- 正式模板仍由应用解析权限、节点纳入状态与范围，本SQL不替代它们。
SET @demo_template_id = 910030010;
SET @demo_year = 2026;
SELECT
  SUM(CASE WHEN m.data_status=2 THEN NULL ELSE m.carbon_emission END) AS raw_carbon,
  SUM(CASE WHEN m.data_status=2 THEN NULL ELSE m.adjusted_carbon_emission END) AS adjusted_carbon,
  SUM(CASE WHEN m.data_status=2 THEN NULL
           WHEN m.total_emission_calc_method=1 THEN m.adjusted_carbon_emission
           WHEN m.total_emission_calc_method=2 THEN m.carbon_emission END) AS adopted_carbon,
  COUNT(*) AS generated_monthly_rows
FROM emission_collection_node_data_month m
WHERE m.year=@demo_year
  AND EXISTS (
    SELECT 1 FROM emission_node_config c
    JOIN emission_node n ON n.id=c.node_id
    WHERE n.template_id=@demo_template_id
      AND c.collection_point_type=m.collection_point_type
      AND c.collection_point_id=m.collection_point_id
  );
-- 机辆演示2026应为RAW=40572.122080000，ADJUSTED=43838.515526400，ADOPTED=42079.899052800；59条实际月度行。
-- EXITS按物理类型+ID匹配，重复引用电表不会重复加入。
