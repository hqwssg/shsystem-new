-- 物理采集点当前最新的月度核算数据。
-- 本迁移不回填历史任务；重复执行不会修改既有月度数据。
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS emission_collection_node_data_month (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    year INT NOT NULL COMMENT '统计年份',
    month TINYINT NOT NULL COMMENT '统计月份（1-12）',
    collection_point_type TINYINT NOT NULL COMMENT '采集点类型：1-电力表，2-化石燃料，3-外购热能',
    collection_point_id BIGINT NOT NULL COMMENT '物理采集点ID，由collection_point_type确定对应采集点表',
    emission_category VARCHAR(100) COMMENT '能耗品种大类',
    emission_subcategory VARCHAR(100) COMMENT '能耗品种小类',
    carbon_emission_factor DECIMAL(15,6) COMMENT '本次核算实际采用的碳排放因子',
    carbon_emission_factor_unit VARCHAR(100) COMMENT '本次核算实际采用的因子单位',
    carbon_emission_unit VARCHAR(30) COMMENT '碳排放结果统一单位，新核算固定为tCO2e',
    is_cumulative TINYINT DEFAULT 0 COMMENT '是否累加量：1-是，0-否',
    is_mobile_source TINYINT DEFAULT 0 COMMENT '是否移动源：1-是，0-否',
    measurement_unit VARCHAR(50) COMMENT '计量单位',
    energy_category_l1 VARCHAR(50) COMMENT '能耗一级分类编码',
    energy_category_l2 VARCHAR(50) COMMENT '能耗二级分类编码',
    energy_category_l3 VARCHAR(50) COMMENT '能耗三级分类编码',
    energy_use_category VARCHAR(100) COMMENT '能耗用途分类',
    energy_measurement_value DECIMAL(18,6) COMMENT '月度能耗计量值',
    carbon_emission DECIMAL(18,9) COMMENT '折算的月度碳排放量（tCO2e）',
    adjusted_energy_value DECIMAL(18,6) COMMENT '经过计算修正后的月度能耗计量值',
    rollover_applied BOOLEAN DEFAULT FALSE COMMENT '本次活动量是否使用归零修正',
    rollover_threshold DECIMAL(18,6) COMMENT '本次核算采用的归零阈值快照',
    adjusted_carbon_emission DECIMAL(18,9) COMMENT '经过计算修正后的月度碳排放量（tCO2e）',
    total_emission_calc_method TINYINT DEFAULT 1 COMMENT '总排放核算方式：1-按修正值，2-按原始值',
    collection_record_start_date DATE COMMENT '本月选用采集记录的起始日期',
    collection_record_end_date DATE COMMENT '本月选用采集记录的截止日期',
    data_status TINYINT COMMENT '数据状态：1-完整，2-没有数据，3-不完整，4-超范围，5-不完整且超范围',
    data_missing_description VARCHAR(500) COMMENT '数据缺失或超限说明',
    energy_attribution_dept_id BIGINT COMMENT '能耗归属部门ID',
    energy_attribution_station_id BIGINT COMMENT '能耗归属站点/区间ID',
    created_by BIGINT COMMENT '创建人ID',
    updated_by BIGINT COMMENT '更新人ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_collection_point_year_month UNIQUE (collection_point_type, collection_point_id, year, month),
    INDEX idx_month_year_month (year, month),
    INDEX idx_month_data_status (data_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='碳排放物理采集点月度核算数据表';

-- 某些本地或存量环境可能已由JPA先创建表；此时CREATE TABLE IF NOT EXISTS
-- 不会补齐正式索引，因此按information_schema幂等补建。
SET @month_year_index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'emission_collection_node_data_month'
      AND index_name = 'idx_month_year_month'
);
SET @month_year_index_ddl = IF(
    @month_year_index_exists = 0,
    'CREATE INDEX idx_month_year_month ON emission_collection_node_data_month (year, month)',
    'SELECT 1'
);
PREPARE month_year_index_stmt FROM @month_year_index_ddl;
EXECUTE month_year_index_stmt;
DEALLOCATE PREPARE month_year_index_stmt;

SET @month_status_index_exists = (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'emission_collection_node_data_month'
      AND index_name = 'idx_month_data_status'
);
SET @month_status_index_ddl = IF(
    @month_status_index_exists = 0,
    'CREATE INDEX idx_month_data_status ON emission_collection_node_data_month (data_status)',
    'SELECT 1'
);
PREPARE month_status_index_stmt FROM @month_status_index_ddl;
EXECUTE month_status_index_stmt;
DEALLOCATE PREPARE month_status_index_stmt;
