-- ============================================================
-- 更新脚本 2026-10-16
-- 变更：新增"碳排放数据不确定性分析（DQI+MCS）"模块表结构，共 9 张表。
--       依据《技术实现方案-铁路碳排放数据不确定性分析-DQI-MCS》V2.0：
--       1) uncertainty_ruleset          DQI 规则库版本表（I5，含维度权重/δ表/标定信息）
--       2) uncertainty_dimension_rule   规则库维度规则表（mapping/band/direct_score）
--       3) uncertainty_source_meta      排放源元信息表（I1，快照自核算结果+人工补录）
--       4) uncertainty_score            DQI 评分表（I2，建议分+最终分+来源）
--       5) uncertainty_audit            评分变更审计表（O6，改前/改后留痕）
--       6) uncertainty_scope_baseline   Scope 级完整性基准表（I6）
--       7) uncertainty_run              模拟运行表（M3-M5 结果、O2/O3/O4）
--       8) uncertainty_run_scope        Scope 级完整性评估表（O7）
--       9) uncertainty_param_result     参数级归一化与分布参数表（O1）
-- 说明：calculation_template_id 逻辑指向 emission_calculation_template.id，
--       不建物理外键，避免与核心核算生命周期耦合；模块内部表间建物理外键
--       （ON DELETE CASCADE）。source_node_id / collection_node_data_id 为逻辑
--       回溯引用，不建物理外键。
-- 幂等：先判断表是否存在，可重复执行。
-- ============================================================

SET SQL_SAFE_UPDATES = 0;

-- ------------------------------------------------------------
-- 1) DQI 规则库版本表
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_ruleset');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_ruleset (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        ruleset_version VARCHAR(50) NOT NULL COMMENT ''规则库版本号，如 DQI-RULES-2026.12'',
        effective_date DATE COMMENT ''生效日期'',
        reviewer VARCHAR(100) COMMENT ''规则库审核人'',
        dimension_weights JSON COMMENT ''按 param_type 的维度权重：{"AD":{"A1":1.0,...},"EF":{"E1":1.0,...}}'',
        calibration_meta JSON COMMENT ''δ表实证标定信息（来源/样本量/日期/对照结论），未标定则报告强制声明'',
        delta_table JSON COMMENT ''SDQI→支撑半宽δ映射表，默认 5.0→5,4.5→8,4.0→12,3.5→16,3.0→20,2.5→30,2.0→40,1.5→60,1.0→100'',
        coverage_delta_cap DECIMAL(5,2) NOT NULL DEFAULT 30 COMMENT ''Scope级 delta_cov_percent 封顶值（%）'',
        coverage_alpha DECIMAL(6,2) NOT NULL DEFAULT 15 COMMENT ''Scope级单侧因子 ξ_cov 的 Beta 参数 α_cov（固定15，Beta(1,α_cov)）'',
        change_reason VARCHAR(500) COMMENT ''本次升版变更理由（权重/启用状态变更必须填写）'',
        created_by VARCHAR(100) COMMENT ''创建人'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        UNIQUE KEY uk_ruleset_version (ruleset_version)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''DQI规则库版本表（不确定性分析）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2) 规则库维度规则表
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_dimension_rule');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_dimension_rule (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        ruleset_id BIGINT NOT NULL COMMENT ''规则库ID，关联 uncertainty_ruleset.id'',
        applies_to VARCHAR(10) NOT NULL COMMENT ''适用参数类型：AD / EF（单值）'',
        dim_code VARCHAR(10) NOT NULL COMMENT ''维度编号：AD 用 A1/A2/A4/A5/A6，EF 用 E1-E6'',
        dim_name VARCHAR(100) NOT NULL COMMENT ''维度中文名称'',
        enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT ''是否启用：1-是，0-否（停用后∑Qmin/∑Qmax自动重算）'',
        weight DECIMAL(6,3) NOT NULL DEFAULT 1.0 COMMENT ''维度权重，须≥0，=0等效禁用该维度'',
        driver VARCHAR(64) NOT NULL COMMENT ''驱动字段名或派生量名（如 ad_metering_tier / delta_year）'',
        rule_type VARCHAR(20) NOT NULL COMMENT ''规则类型：mapping-枚举查表 / band-数值分段 / direct_score-直接评分'',
        entries JSON COMMENT ''mapping:{枚举值:分值}；band:[[下界(含),上界(不含),分值],...]；direct_score 为空'',
        null_policy VARCHAR(30) NOT NULL DEFAULT ''to_manual'' COMMENT ''缺失策略：to_manual / default_with_flag / neutral'',
        neutral_score INT COMMENT ''中性分值（null_policy=neutral 时必填，如 A2 不适用取3）'',
        neutral_when_value VARCHAR(64) COMMENT ''触发中性分的枚举取值（如 calib_not_applicable）'',
        default_value VARCHAR(64) COMMENT ''默认填充值（null_policy=default_with_flag 时必填，如 direct_metered）'',
        mark_default_filled TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''默认填充时是否标注 default_filled=true'',
        valid_range JSON COMMENT ''band 有效域 [下界,上界]，超出视为越域转人工（不构成加载失败）'',
        out_of_range_warning VARCHAR(500) COMMENT ''越域警告文本'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        UNIQUE KEY uk_ruleset_type_dim (ruleset_id, applies_to, dim_code),
        CONSTRAINT fk_unc_dim_rule_ruleset FOREIGN KEY (ruleset_id)
            REFERENCES uncertainty_ruleset (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''DQI规则库维度规则表''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 3) 排放源元信息表（I1）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_source_meta');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_source_meta (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        calculation_template_id BIGINT NOT NULL COMMENT ''核算任务ID，逻辑关联 emission_calculation_template.id'',
        collection_node_data_id BIGINT COMMENT ''采集节点核算数据ID，逻辑回溯 emission_collection_node_data.id'',
        source_node_id BIGINT COMMENT ''源节点ID，逻辑回溯 emission_node.id'',
        source_name VARCHAR(200) NOT NULL COMMENT ''排放源名称'',
        scope VARCHAR(50) COMMENT ''Scope类别（emission_category：scope1/scope2/scope3等）'',
        emission_subcategory VARCHAR(100) COMMENT ''排放数据小类（emission_subcategory）'',
        energy_type VARCHAR(50) COMMENT ''燃料/能源类型'',
        ad_value DECIMAL(24,8) COMMENT ''活动数据AD名义值（核算单位能耗值）'',
        ad_unit VARCHAR(30) COMMENT ''AD单位（unit_code）'',
        ef_value DECIMAL(24,12) COMMENT ''排放因子EF名义值'',
        ef_unit VARCHAR(30) COMMENT ''EF单位'',
        emission_value DECIMAL(24,8) COMMENT ''排放量E=AD×EF（tCO2）'',
        data_source VARCHAR(500) COMMENT ''数据来源说明'',
        ad_metering_tier VARCHAR(40) COMMENT ''A1驱动：online_meter/manual_ledger/statistical_report/literature_thirdparty/default_or_estimated'',
        ad_meter_calibration VARCHAR(40) COMMENT ''A2驱动：calib_valid_cert/.../calib_not_applicable'',
        ad_data_year INT COMMENT ''A5驱动：AD数据年份'',
        ad_geo_basis VARCHAR(40) COMMENT ''A4驱动：direct_metered/ledger_complete/allocated/analogized/default_value'',
        ad_data_collection_quality INT COMMENT ''A6驱动：数据采集质量1-5直接评分（excluded类自动中性3分）'',
        ef_source_authority VARCHAR(40) COMMENT ''E1驱动：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated'',
        ef_completeness_scope VARCHAR(40) COMMENT ''E2驱动：full/minor_missing/partial_missing/major_only/unknown'',
        ef_data_region VARCHAR(40) COMMENT ''E3驱动：in_boundary/same_grid/national/similar_economy/other_country'',
        ef_data_year INT COMMENT ''E4驱动：EF数据年份'',
        ef_tech_applicability VARCHAR(40) COMMENT ''E5驱动：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default'',
        ef_conversion_chain VARCHAR(40) COMMENT ''E6驱动：direct_match/standard_single/multi_step/derived_from_other/unclear'',
        deprecated_fields_warning VARCHAR(1000) COMMENT ''A3废弃字段检测警告（导入不阻断）'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT ''更新时间'',
        UNIQUE KEY uk_tpl_coll (calculation_template_id, collection_node_data_id),
        KEY idx_unc_source_tpl (calculation_template_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''不确定性分析排放源元信息表（I1）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 4) DQI 评分表（I2，每参数每维度一行）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_score');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_score (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        source_meta_id BIGINT NOT NULL COMMENT ''排放源元信息ID，关联 uncertainty_source_meta.id'',
        param_type VARCHAR(10) NOT NULL COMMENT ''参数类型：AD / EF'',
        dim_code VARCHAR(10) NOT NULL COMMENT ''维度编号'',
        weight DECIMAL(6,3) NOT NULL DEFAULT 1.0 COMMENT ''评分时使用的维度权重（快照）'',
        suggested_score INT COMMENT ''M2a建议分（缺失转人工时为NULL，禁止默认填充）'',
        score_evidence VARCHAR(1000) COMMENT ''判定依据（驱动字段取值+命中区间）'',
        auto_scoring_status VARCHAR(20) DEFAULT ''complete'' COMMENT ''自动评分状态：complete/partial/unavailable'',
        final_score INT COMMENT ''最终分（1-5整数，人工确认/覆盖后必填）'',
        score_source VARCHAR(30) COMMENT ''分值来源：auto/manual_override/expert_override/neutral/auto_neutral_excluded'',
        override_reason VARCHAR(1000) COMMENT ''人工覆盖理由（score_source=manual_override时必填）'',
        a6_source VARCHAR(30) COMMENT ''A6来源标记：normal/neutral_excluded（仅A6维度使用）'',
        default_filled TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''ad_geo_basis留空被默认填充标记'',
        warnings VARCHAR(500) COMMENT ''该维度触发的警告编号（逗号分隔）'',
        ruleset_version VARCHAR(50) NOT NULL COMMENT ''评分所用规则库版本（永久绑定）'',
        reviewer VARCHAR(100) COMMENT ''复核人'',
        review_time DATETIME COMMENT ''复核时间'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT ''更新时间'',
        UNIQUE KEY uk_source_param_dim (source_meta_id, param_type, dim_code),
        CONSTRAINT fk_unc_score_source FOREIGN KEY (source_meta_id)
            REFERENCES uncertainty_source_meta (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''DQI评分表（I2）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 5) 评分变更审计表（O6）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_audit');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_audit (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        score_id BIGINT NOT NULL COMMENT ''评分记录ID，关联 uncertainty_score.id'',
        source_meta_id BIGINT NOT NULL COMMENT ''排放源元信息ID（冗余，便于按源查询）'',
        param_type VARCHAR(10) NOT NULL COMMENT ''参数类型'',
        dim_code VARCHAR(10) NOT NULL COMMENT ''维度编号'',
        old_score INT COMMENT ''改前最终分'',
        new_score INT COMMENT ''改后最终分'',
        old_source VARCHAR(30) COMMENT ''改前分值来源'',
        new_source VARCHAR(30) COMMENT ''改后分值来源'',
        override_reason VARCHAR(1000) COMMENT ''覆盖理由'',
        reviewer VARCHAR(100) COMMENT ''复核人'',
        review_time DATETIME COMMENT ''复核时间'',
        ruleset_version VARCHAR(50) COMMENT ''规则库版本'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        KEY idx_unc_audit_score (score_id),
        KEY idx_unc_audit_source (source_meta_id),
        CONSTRAINT fk_unc_audit_score FOREIGN KEY (score_id)
            REFERENCES uncertainty_score (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''DQI评分变更审计表（O6）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 6) Scope 级完整性基准表（I6）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_scope_baseline');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_scope_baseline (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        calculation_template_id BIGINT NOT NULL COMMENT ''核算任务ID，逻辑关联 emission_calculation_template.id'',
        scope VARCHAR(50) NOT NULL COMMENT ''Scope类别'',
        benchmark_qty DECIMAL(24,8) COMMENT ''独立自上而下基准量（必须为正；留空则该Scope走measured/disabled）'',
        benchmark_unit VARCHAR(30) COMMENT ''基准量单位（须与Scope内AD可比）'',
        benchmark_source VARCHAR(200) COMMENT ''基准来源：供电局结算单/设施台账/运量反算/上年清单等'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT ''更新时间'',
        UNIQUE KEY uk_tpl_scope (calculation_template_id, scope)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''Scope级完整性基准表（I6）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 7) 模拟运行表（M3-M5 汇总结果）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_run');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_run (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        calculation_template_id BIGINT NOT NULL COMMENT ''核算任务ID，逻辑关联 emission_calculation_template.id'',
        ruleset_version VARCHAR(50) NOT NULL COMMENT ''本次运行使用的规则库版本'',
        n_iterations INT NOT NULL DEFAULT 10000 COMMENT ''MCS迭代次数（1000-1000000）'',
        confidence_level DECIMAL(4,3) NOT NULL DEFAULT 0.950 COMMENT ''置信水平'',
        random_seed BIGINT COMMENT ''随机种子（固定可复现）'',
        completeness_scope_level VARCHAR(20) NOT NULL DEFAULT ''scope'' COMMENT ''完整性作用范围：boundary/scope/category'',
        status VARCHAR(20) NOT NULL DEFAULT ''RUNNING'' COMMENT ''运行状态：RUNNING/SUCCESS/FAILED'',
        error_message TEXT COMMENT ''失败原因'',
        e_point_raw DECIMAL(28,8) COMMENT ''记录下锚点估计：ΣE_i（无完整性修正）'',
        e_point_cov DECIMAL(28,8) COMMENT ''完整性修正后点估计：Σ_g(E[g]×E[ξ_cov(g)])，验证基准'',
        uplift_percent DECIMAL(10,4) COMMENT ''上抬百分比：(E_point_cov-E_point_raw)/E_point_raw×100%'',
        total_mean DECIMAL(28,8) COMMENT ''MCS样本均值μ_E'',
        total_median DECIMAL(28,8) COMMENT ''MCS样本中位数'',
        total_std DECIMAL(28,8) COMMENT ''MCS样本标准差σ_E'',
        cv_percent DECIMAL(10,4) COMMENT ''变异系数CV=σ_E/μ_E×100%'',
        ci_lower DECIMAL(28,8) COMMENT ''置信区间下界（分位数法）'',
        ci_upper DECIMAL(28,8) COMMENT ''置信区间上界'',
        quantiles JSON COMMENT ''分位数集合 {p5,p25,p50,p75,p95}'',
        dev_mean_percent DECIMAL(10,4) COMMENT ''均值偏差：(μ_E-E_point_cov)/E_point_cov×100%，|≤2%|为无偏'',
        dev_median_percent DECIMAL(10,4) COMMENT ''中位数偏差（|≤5%|）'',
        point_cov_in_ci TINYINT(1) COMMENT ''E_point_cov是否落入置信区间'',
        raw_le_cov TINYINT(1) COMMENT ''下锚关系：E_point_raw≤E_point_cov'',
        uncertainty_level VARCHAR(10) COMMENT ''不确定性等级：低/中/较高/高（按CV分级）'',
        verification_conclusion TEXT COMMENT ''验证结论文本（O4）'',
        warnings JSON COMMENT ''本次运行触发的警告编号及内容集合'',
        started_at DATETIME COMMENT ''开始时间'',
        finished_at DATETIME COMMENT ''完成时间'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        KEY idx_unc_run_tpl (calculation_template_id),
        KEY idx_unc_run_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''不确定性分析模拟运行表''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 8) Scope 级完整性评估表（O7，每次运行每 Scope 一行）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_run_scope');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_run_scope (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        run_id BIGINT NOT NULL COMMENT ''模拟运行ID，关联 uncertainty_run.id'',
        scope VARCHAR(50) NOT NULL COMMENT ''Scope类别'',
        scope_emission DECIMAL(28,8) COMMENT ''该Scope记录级排放量小计E[g]'',
        basis VARCHAR(30) NOT NULL COMMENT ''判据类型：benchmark_measured/measured/disabled'',
        benchmark_qty DECIMAL(24,8) COMMENT ''独立基准量（无基准为NULL）'',
        benchmark_source VARCHAR(200) COMMENT ''基准来源'',
        r_benchmark DECIMAL(10,6) COMMENT ''规模完整性：ΣAD_i/benchmark_qty'',
        r_measured DECIMAL(10,6) COMMENT ''排放量加权计量支撑度'',
        point_ratio_xn DECIMAL(10,6) COMMENT ''点数比x/n（仅诊断，不参与定价）'',
        delta_cov_percent DECIMAL(6,3) NOT NULL DEFAULT 0 COMMENT ''Scope级δ_cov（由r_eff直接查分段表，封顶coverage_delta_cap）'',
        e_xi_cov DECIMAL(10,6) NOT NULL DEFAULT 1 COMMENT ''E[ξ_cov]=1+(δ_cov/100)/16'',
        disclosure TEXT COMMENT ''basis=disabled时的强制披露文案'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        UNIQUE KEY uk_run_scope (run_id, scope),
        CONSTRAINT fk_unc_run_scope_run FOREIGN KEY (run_id)
            REFERENCES uncertainty_run (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''Scope级完整性评估表（O7）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 9) 参数级归一化与分布参数表（O1，每次运行每参数一行）
-- ------------------------------------------------------------
SET @exist := (SELECT COUNT(*) FROM information_schema.TABLES
    WHERE table_schema = DATABASE() AND table_name = 'uncertainty_param_result');
SET @sql := IF(@exist = 0,
    'CREATE TABLE uncertainty_param_result (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT ''主键ID'',
        run_id BIGINT NOT NULL COMMENT ''模拟运行ID，关联 uncertainty_run.id'',
        source_meta_id BIGINT NOT NULL COMMENT ''排放源元信息ID，关联 uncertainty_source_meta.id'',
        param_type VARCHAR(10) NOT NULL COMMENT ''参数类型：AD / EF'',
        ruleset_version VARCHAR(50) NOT NULL COMMENT ''规则库版本'',
        sum_q_w DECIMAL(10,3) COMMENT ''加权总分∑Q_w=Σ(w_j×s_j)'',
        sum_q_min_w DECIMAL(10,3) COMMENT ''归一化下界∑Qmin_w'',
        sum_q_max_w DECIMAL(10,3) COMMENT ''归一化上界∑Qmax_w'',
        x_percent DECIMAL(8,4) COMMENT ''归一化质量分数x(%)'',
        sdqi DECIMAL(3,1) COMMENT ''SDQI（表4-4，1.0-5.0步进0.5）'',
        beta_alpha DECIMAL(12,4) COMMENT ''Beta分布形状参数α=SDQI²'',
        beta_beta DECIMAL(12,4) COMMENT ''Beta分布形状参数β=SDQI²'',
        delta_percent DECIMAL(8,4) COMMENT ''支撑半宽δ（SDQI查δ表，名义值%）'',
        support_low_factor DECIMAL(8,5) COMMENT ''支撑区间下因子1-δ/100'',
        support_high_factor DECIMAL(8,5) COMMENT ''支撑区间上因子1+δ/100'',
        warnings VARCHAR(500) COMMENT ''该参数触发的警告编号'',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT ''创建时间'',
        UNIQUE KEY uk_run_source_param (run_id, source_meta_id, param_type),
        CONSTRAINT fk_unc_param_run FOREIGN KEY (run_id)
            REFERENCES uncertainty_run (id) ON DELETE CASCADE,
        CONSTRAINT fk_unc_param_source FOREIGN KEY (source_meta_id)
            REFERENCES uncertainty_source_meta (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT=''参数级归一化与Beta分布参数表（O1）''',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
