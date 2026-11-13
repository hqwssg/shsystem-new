-- 核算节点与分公司最新月度统计表。
-- 不回填历史核算任务；重复执行不会修改任何业务数据。
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS emission_calc_node_summary_month (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    template_id BIGINT NOT NULL COMMENT '核算模板ID（emission_template.id）',
    source_node_id BIGINT NOT NULL COMMENT '设计态核算/根节点ID（emission_node.id）',
    parent_source_node_id BIGINT COMMENT '设计态父节点ID（emission_node.id）',
    year INT NOT NULL COMMENT '统计年份',
    month TINYINT NOT NULL COMMENT '统计月份（1-12）',
    node_level INT NOT NULL COMMENT '节点在核算树中的层级，根节点=1',
    is_leaf_calc_node TINYINT NOT NULL DEFAULT 0 COMMENT '是否最底层核算节点：1-是，0-否',
    emission_category VARCHAR(100) COMMENT '排放数据大类编码',
    emission_subcategory VARCHAR(100) NOT NULL COMMENT '排放数据小类编码',
    direct_energy_value DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '本节点直属采集点标准核算单位能耗',
    direct_carbon_emission DECIMAL(18,9) NOT NULL DEFAULT 0 COMMENT '本节点直属采集点碳排放（tCO2e）',
    subtotal_energy_value DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '本节点子树标准核算单位能耗小计',
    subtotal_carbon_emission DECIMAL(18,9) NOT NULL DEFAULT 0 COMMENT '本节点子树碳排放小计（tCO2e）',
    calculation_unit_code VARCHAR(30) COMMENT '排放小类核算单位代码',
    carbon_emission_factor DECIMAL(18,9) COMMENT '本节点该小类等效碳因子',
    summary_source TINYINT NOT NULL COMMENT '汇总来源位：1-直属采集点，2-子核算节点，3-两者',
    result_status TINYINT NOT NULL DEFAULT 1 COMMENT '结果状态：1-子树采集数据完整，2-至少一个采集点异常',
    missing_collection_point_ids VARCHAR(500) COMMENT '直属异常type=3模板采集节点ID，英文逗号分隔',
    created_by BIGINT COMMENT '创建人ID', updated_by BIGINT COMMENT '更新人ID',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_node_month_subcategory UNIQUE (template_id, source_node_id, year, month, emission_subcategory),
    INDEX idx_node_month_template_cycle (template_id, year, month),
    INDEX idx_node_month_status (result_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='核算节点最新月度能耗与碳排放汇总表';

CREATE TABLE IF NOT EXISTS emission_company_energy_summary_month (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    company_dept_id BIGINT NOT NULL COMMENT '分公司部门ID',
    year INT NOT NULL COMMENT '统计年份', month TINYINT NOT NULL COMMENT '统计月份（1-12）',
    energy_category_l1 VARCHAR(50) NOT NULL COMMENT '能耗一级分类编码',
    emission_category VARCHAR(100) COMMENT '排放数据大类编码',
    emission_subcategory VARCHAR(100) NOT NULL COMMENT '排放数据小类编码',
    standard_energy_value DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '按该小类报告标准单位换算后的能耗',
    carbon_emission DECIMAL(18,9) NOT NULL DEFAULT 0 COMMENT '碳排放量（tCO2e）',
    carbon_emission_factor DECIMAL(18,9) COMMENT '该分组等效碳因子',
    calculation_unit_code VARCHAR(30) NOT NULL COMMENT '标准能耗单位代码',
    result_status TINYINT NOT NULL DEFAULT 1 COMMENT '结果状态：1-采集数据完整，2-至少一个采集点异常',
    ingest_status TINYINT NOT NULL DEFAULT 0 COMMENT '入库状态：0-未入库，1-已入库，2-入库失败',
    created_by BIGINT COMMENT '创建人ID', updated_by BIGINT COMMENT '更新人ID',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT uk_company_month_energy_subcategory UNIQUE
        (company_dept_id, year, month, energy_category_l1, emission_subcategory),
    INDEX idx_company_month_cycle (year, month),
    INDEX idx_company_month_status (result_status, ingest_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分公司最新月度标准能耗与碳排放统计表';

-- 若存量环境曾由JPA先行建表，CREATE TABLE IF NOT EXISTS不会补约束和索引，逐项幂等补齐。
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE()
    AND table_name='emission_calc_node_summary_month' AND index_name='uk_node_month_subcategory')=0,
    'ALTER TABLE emission_calc_node_summary_month ADD CONSTRAINT uk_node_month_subcategory UNIQUE (template_id,source_node_id,year,month,emission_subcategory)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE()
    AND table_name='emission_calc_node_summary_month' AND index_name='idx_node_month_template_cycle')=0,
    'CREATE INDEX idx_node_month_template_cycle ON emission_calc_node_summary_month (template_id,year,month)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE()
    AND table_name='emission_calc_node_summary_month' AND index_name='idx_node_month_status')=0,
    'CREATE INDEX idx_node_month_status ON emission_calc_node_summary_month (result_status)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE()
    AND table_name='emission_company_energy_summary_month' AND index_name='uk_company_month_energy_subcategory')=0,
    'ALTER TABLE emission_company_energy_summary_month ADD CONSTRAINT uk_company_month_energy_subcategory UNIQUE (company_dept_id,year,month,energy_category_l1,emission_subcategory)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE()
    AND table_name='emission_company_energy_summary_month' AND index_name='idx_company_month_cycle')=0,
    'CREATE INDEX idx_company_month_cycle ON emission_company_energy_summary_month (year,month)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE()
    AND table_name='emission_company_energy_summary_month' AND index_name='idx_company_month_status')=0,
    'CREATE INDEX idx_company_month_status ON emission_company_energy_summary_month (result_status,ingest_status)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
