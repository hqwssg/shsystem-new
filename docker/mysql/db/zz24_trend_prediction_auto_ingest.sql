-- 碳排放趋势预测自动使用分公司月度能耗统计的全局开关。
-- 只建立参数契约；重复执行不会覆盖管理员已经设置的值或审计时间。
SET NAMES utf8mb4;

INSERT INTO sys_config
    (config_name, config_key, config_value, config_type, create_by, create_time, remark)
SELECT
    '碳排放趋势预测-自动使用分公司月度能耗统计',
    'carbon.trend-prediction.auto-ingest-company-monthly-data',
    'false', 'Y', 'admin', CURRENT_TIMESTAMP,
    '是否自动将新生成的分公司月度能耗统计用于碳排放趋势预测。true：开启；false：关闭。'
WHERE NOT EXISTS (
    SELECT 1 FROM sys_config
    WHERE config_key = 'carbon.trend-prediction.auto-ingest-company-monthly-data'
);
