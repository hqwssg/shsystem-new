-- =====================================================================
-- 铁路碳排放趋势预测模块 —— 数据库结构
-- 目标库：carbon_emissions（与大平台同库）
-- 所有本模块表统一使用 prediction_ 前缀
-- 字符集：utf8mb4 / InnoDB
-- 说明：脚本可重复执行；不删除平台已有表。
-- =====================================================================

CREATE DATABASE IF NOT EXISTS `carbon_emissions`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `carbon_emissions`;

-- ---------------------------------------------------------------------
-- 1. 组织维表（与平台 sys_dept / sys_carbon_company 对齐）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_org` (
  `org_id`            VARCHAR(16)  NOT NULL COMMENT '模块内组织编码：SHL/JLG/SNF/YPF',
  `org_name`          VARCHAR(64)  NOT NULL COMMENT '组织名称',
  `org_level`         TINYINT      NOT NULL DEFAULT 2 COMMENT '层级：1=公司 2=分公司',
  `parent_org_id`     VARCHAR(16)  DEFAULT NULL COMMENT '上级组织编码',
  `platform_dept_id`  BIGINT       DEFAULT NULL COMMENT '平台 sys_dept.dept_id，用于集成映射',
  `province`          VARCHAR(32)  DEFAULT NULL COMMENT '主要经营省份',
  `heating_months`    VARCHAR(32)  DEFAULT NULL COMMENT '供暖月份，如 1,2,3,11,12',
  `latitude`          DECIMAL(8,4) DEFAULT NULL,
  `longitude`         DECIMAL(8,4) DEFAULT NULL,
  `status`            VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active/inactive',
  `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`org_id`),
  UNIQUE KEY `uk_platform_dept` (`platform_dept_id`),
  KEY `idx_parent` (`parent_org_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='预测模块组织维表';

-- ---------------------------------------------------------------------
-- 2. 能源/活动品种维表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_energy_var` (
  `var_id`        VARCHAR(32) NOT NULL COMMENT '品种编码',
  `var_name`      VARCHAR(64) NOT NULL COMMENT '中文名称',
  `unit`          VARCHAR(32) NOT NULL COMMENT '权威单位',
  `var_category`  VARCHAR(32) NOT NULL COMMENT 'fuel/electricity/heat/operation/target',
  `is_traction`   TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否牵引电力',
  `is_target`     TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否建模目标',
  `sort_order`    INT         NOT NULL DEFAULT 0,
  `remark`        VARCHAR(256) DEFAULT NULL,
  PRIMARY KEY (`var_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='能源与活动品种维表';

-- ---------------------------------------------------------------------
-- 3. 排放因子表（按生效期切片，显式标记统计口径切换）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_emission_factor` (
  `factor_id`        BIGINT       NOT NULL AUTO_INCREMENT,
  `var_id`           VARCHAR(32)  NOT NULL,
  `factor_value`     DECIMAL(18,8) NOT NULL,
  `factor_unit`      VARCHAR(32)  NOT NULL COMMENT '如 tCO2/MWh、tCO2/t、tCO2/万m3',
  `factor_version`   VARCHAR(64)  NOT NULL DEFAULT 'legacy' COMMENT '因子版本，如 EF-ELEC-2025',
  `effective_from`   DATE         NOT NULL,
  `effective_to`     DATE         DEFAULT NULL COMMENT 'NULL 表示当前有效',
  `factor_source`    VARCHAR(64)  DEFAULT NULL,
  `is_caliber_change` TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '1=核算口径切换点，需做可比口径还原',
  `policy_basis`     VARCHAR(512) DEFAULT NULL,
  `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`factor_id`),
  UNIQUE KEY `uk_var_from` (`var_id`,`effective_from`),
  KEY `idx_effective` (`effective_from`,`effective_to`),
  KEY `idx_var_version` (`var_id`,`factor_version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='排放因子维表（含口径切换标记）';

-- ---------------------------------------------------------------------
-- 4. 供热面积折算系数等口径规则
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_caliber_rule` (
  `rule_id`        VARCHAR(64) NOT NULL,
  `org_id`         VARCHAR(16) NOT NULL,
  `rule_type`      VARCHAR(32) NOT NULL COMMENT 'heat_area_factor / grid_factor',
  `effective_from` DATE        NOT NULL,
  `effective_to`   DATE        DEFAULT NULL,
  `rule_value`     DECIMAL(18,8) NOT NULL,
  `unit`           VARCHAR(32) NOT NULL,
  `rule_version`   VARCHAR(64) NOT NULL DEFAULT 'legacy' COMMENT '规则版本，如 CAL-2025',
  `source`         VARCHAR(512) DEFAULT NULL,
  `note`           VARCHAR(512) DEFAULT NULL,
  `created_at`     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`rule_id`),
  KEY `idx_org_type` (`org_id`,`rule_type`,`effective_from`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='核算口径规则（面积折热系数、电网因子等）';

-- ---------------------------------------------------------------------
-- 5. 月度活动数据事实表（长表）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_activity_monthly` (
  `id`              BIGINT       NOT NULL AUTO_INCREMENT,
  `org_id`          VARCHAR(16)  NOT NULL,
  `period`          DATE         NOT NULL COMMENT '统计月首日',
  `var_id`          VARCHAR(32)  NOT NULL,
  `value`           DECIMAL(20,6) DEFAULT NULL COMMENT '物理/可比口径值',
  `reported_value`  DECIMAL(20,6) DEFAULT NULL COMMENT '报表口径值（热力口径切换时与 value 不同）',
  `unit`            VARCHAR(32)  NOT NULL,
  `source_status`   VARCHAR(32)  NOT NULL DEFAULT '原始' COMMENT '原始/推算/补全/口径还原/异常剔除/无此项',
  `is_estimated`    TINYINT(1)   NOT NULL DEFAULT 0,
  `quality_status`  VARCHAR(16)  NOT NULL DEFAULT 'valid' COMMENT 'valid/pending/excluded',
  `data_flag`       VARCHAR(64)  DEFAULT NULL COMMENT '结构断点、口径切换、待核实等标记',
  `batch_id`        VARCHAR(40)  DEFAULT NULL,
  `data_version`    VARCHAR(40)  DEFAULT NULL,
  `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_org_period_var` (`org_id`,`period`,`var_id`),
  KEY `idx_org_period` (`org_id`,`period`),
  KEY `idx_var_period` (`var_id`,`period`),
  KEY `idx_quality` (`quality_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='月度活动数据事实表（长表，支持版本与质量状态）';

-- ---------------------------------------------------------------------
-- 6. 月度碳排放结果表（报表口径 + 可比口径）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_emission_monthly` (
  `id`                    BIGINT       NOT NULL AUTO_INCREMENT,
  `org_id`                VARCHAR(16)  NOT NULL,
  `period`                DATE         NOT NULL,
  `scope`                 VARCHAR(16)  NOT NULL DEFAULT 'Total',
  `gas_tco2`              DECIMAL(20,6) NOT NULL DEFAULT 0,
  `gasoline_tco2`         DECIMAL(20,6) NOT NULL DEFAULT 0,
  `diesel_tco2`           DECIMAL(20,6) NOT NULL DEFAULT 0,
  `electricity_tco2`      DECIMAL(20,6) NOT NULL DEFAULT 0,
  `heat_tco2`             DECIMAL(20,6) NOT NULL DEFAULT 0,
  `total_reported_tco2`   DECIMAL(20,6) NOT NULL DEFAULT 0 COMMENT '按当年实际因子/热力口径计算',
  `total_comparable_tco2` DECIMAL(20,6) NOT NULL DEFAULT 0 COMMENT '按基准因子与基准热力口径还原，用于建模',
  `electricity_factor`    DECIMAL(18,8) NOT NULL DEFAULT 0,
  `heat_factor`           DECIMAL(18,8) NOT NULL DEFAULT 0,
  `factor_version`        VARCHAR(128) DEFAULT NULL COMMENT '本次使用的因子版本组合',
  `heat_area_factor`      DECIMAL(18,8) DEFAULT NULL COMMENT '本次使用的供热面积系数',
  `factor_source`         VARCHAR(255) DEFAULT NULL COMMENT '因子来源摘要',
  `factor_snapshot`       JSON         DEFAULT NULL COMMENT '本次使用的完整因子快照',
  `calc_method`           VARCHAR(32)  NOT NULL DEFAULT 'activity_x_factor',
  `is_verified`           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '与原始台账 co2_t 恒等式校验',
  `batch_id`              VARCHAR(40)  DEFAULT NULL,
  `data_version`          VARCHAR(40)  DEFAULT NULL,
  `created_at`            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_org_period_scope` (`org_id`,`period`,`scope`),
  KEY `idx_org_period` (`org_id`,`period`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='月度碳排放结果表（报表/可比双口径）';

-- ---------------------------------------------------------------------
-- 7. 异常检测与人工复核表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_anomaly` (
  `id`                   BIGINT       NOT NULL AUTO_INCREMENT,
  `org_id`               VARCHAR(16)  NOT NULL,
  `period`               DATE         NOT NULL,
  `var_id`               VARCHAR(32)  NOT NULL,
  `detect_batch_id`      VARCHAR(40)  NOT NULL,
  `channel`              VARCHAR(16)  NOT NULL DEFAULT 'stl_residual' COMMENT 'raw/stl_residual',
  `score`                DECIMAL(10,6) DEFAULT NULL COMMENT 's = -score_samples',
  `score_percentile`     DECIMAL(6,2)  DEFAULT NULL,
  `level`                VARCHAR(16)  DEFAULT NULL COMMENT '正常/关注/异常/严重异常',
  `category`             VARCHAR(16)  DEFAULT NULL COMMENT 'C1/C2/C3/C4/UNDETERMINED',
  `confidence`           DECIMAL(6,4)  DEFAULT NULL,
  `suggested_disposition` VARCHAR(24) DEFAULT NULL,
  `status`               VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected/auto_closed',
  `final_disposition`    VARCHAR(24)  DEFAULT NULL COMMENT 'keep/correct/exclude/mark_breakpoint',
  `value`                DECIMAL(20,6) DEFAULT NULL,
  `reference_value`      DECIMAL(20,6) DEFAULT NULL,
  `correction_value`     DECIMAL(20,6) DEFAULT NULL,
  `evidence`             VARCHAR(1000) DEFAULT NULL,
  `reviewer`             VARCHAR(64)  DEFAULT NULL,
  `reviewed_at`          DATETIME     DEFAULT NULL,
  `review_note`          VARCHAR(512) DEFAULT NULL,
  `algorithm_version`    VARCHAR(16)  NOT NULL DEFAULT 'v2',
  `raw_score`            DECIMAL(10,6) DEFAULT NULL,
  `resid_score`          DECIMAL(10,6) DEFAULT NULL,
  `joint_score`          DECIMAL(10,6) DEFAULT NULL,
  `channels`             VARCHAR(64)  DEFAULT NULL,
  `context_flags`        VARCHAR(128) DEFAULT NULL,
  `breakpoint_date`      DATE         DEFAULT NULL,
  `breakpoint_stat`      DECIMAL(10,4) DEFAULT NULL,
  `shift_pct`            DECIMAL(10,4) DEFAULT NULL,
  `cv_ratio`             DECIMAL(10,4) DEFAULT NULL,
  `in_breakpoint_window` TINYINT(1)   NOT NULL DEFAULT 0,
  `created_at`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_org_period_var_batch` (`org_id`,`period`,`var_id`,`detect_batch_id`),
  KEY `idx_status` (`status`),
  KEY `idx_org_period` (`org_id`,`period`),
  KEY `idx_level` (`level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='异常检测结果与人工复核状态';

CREATE TABLE IF NOT EXISTS `prediction_anomaly_audit` (
  `id`            BIGINT       NOT NULL AUTO_INCREMENT,
  `anomaly_id`    BIGINT       NOT NULL,
  `action`        VARCHAR(24)  NOT NULL,
  `before_value`  DECIMAL(20,6) DEFAULT NULL,
  `after_value`   DECIMAL(20,6) DEFAULT NULL,
  `operator`      VARCHAR(64)  NOT NULL,
  `note`          VARCHAR(512) DEFAULT NULL,
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_anomaly` (`anomaly_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='异常复核审计（不可变追加）';

CREATE TABLE IF NOT EXISTS `prediction_anomaly_watch` (
  `id`                BIGINT       NOT NULL AUTO_INCREMENT,
  `org_id`            VARCHAR(16)  NOT NULL,
  `period`            DATE         NOT NULL,
  `var_id`            VARCHAR(32)  NOT NULL,
  `level`             VARCHAR(16)  NOT NULL DEFAULT '关注',
  `category`          VARCHAR(16)  DEFAULT NULL,
  `score`             DECIMAL(10,6) DEFAULT NULL,
  `raw_score`         DECIMAL(10,6) DEFAULT NULL,
  `resid_score`       DECIMAL(10,6) DEFAULT NULL,
  `joint_score`       DECIMAL(10,6) DEFAULT NULL,
  `channels`          VARCHAR(64)  DEFAULT NULL,
  `context_flags`     VARCHAR(128) DEFAULT NULL,
  `evidence`          VARCHAR(1000) DEFAULT NULL,
  `algorithm_version` VARCHAR(16)  NOT NULL DEFAULT 'v2',
  `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_org_period_var` (`org_id`,`period`,`var_id`,`algorithm_version`),
  KEY `idx_org_period` (`org_id`,`period`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='关注级异常监控（不进复核队列）';

CREATE TABLE IF NOT EXISTS `prediction_anomaly_calibration` (
  `id`              BIGINT       NOT NULL AUTO_INCREMENT,
  `run_id`          VARCHAR(40)  NOT NULL,
  `org_id`          VARCHAR(16)  NOT NULL,
  `var_id`          VARCHAR(32)  NOT NULL,
  `quantile`        DECIMAL(6,4) NOT NULL,
  `threshold_value` DECIMAL(12,6) DEFAULT NULL,
  `precision_v`     DECIMAL(8,4) DEFAULT NULL,
  `recall_v`        DECIMAL(8,4) DEFAULT NULL,
  `f1`              DECIMAL(8,4) DEFAULT NULL,
  `n_pos`           INT          NOT NULL DEFAULT 0,
  `n_neg`           INT          NOT NULL DEFAULT 0,
  `selected`        TINYINT(1)   NOT NULL DEFAULT 0,
  `note`            VARCHAR(512) DEFAULT NULL,
  `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_run_org_var_q` (`run_id`,`org_id`,`var_id`,`quantile`),
  KEY `idx_org_var` (`org_id`,`var_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='异常阈值/污染率弱标签校准';

CREATE TABLE IF NOT EXISTS `prediction_calendar_event` (
  `id`               BIGINT       NOT NULL AUTO_INCREMENT,
  `event_id`         VARCHAR(48)  NOT NULL,
  `event_type`       VARCHAR(32)  NOT NULL,
  `event_name`       VARCHAR(128) NOT NULL,
  `start_date`       DATE         NOT NULL,
  `end_date`         DATE         NOT NULL,
  `org_id`           VARCHAR(16)  NOT NULL DEFAULT 'ALL',
  `impact_direction` VARCHAR(16)  DEFAULT 'unknown',
  `source`           VARCHAR(512) DEFAULT NULL,
  `note`             VARCHAR(512) DEFAULT NULL,
  `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_event` (`event_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='节假日/疫情/检修日历事件';

-- ---------------------------------------------------------------------
-- 8. 数据接入批次表（幂等）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_ingest_batch` (
  `batch_id`           VARCHAR(40)  NOT NULL,
  `org_id`             VARCHAR(16)  DEFAULT NULL,
  `period_start`       DATE         DEFAULT NULL,
  `period_end`         DATE         DEFAULT NULL,
  `row_count`          INT          NOT NULL DEFAULT 0,
  `anomaly_count`      INT          NOT NULL DEFAULT 0,
  `status`             VARCHAR(24)  NOT NULL DEFAULT 'received' COMMENT 'received/validated/pending_review/completed/rejected',
  `idempotency_key`    VARCHAR(64)  DEFAULT NULL,
  `payload_hash`       VARCHAR(64)  DEFAULT NULL COMMENT '请求体规范化 SHA-256，用于同一 key 的请求一致性校验',
  `override_flag`      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否显式覆盖同月已入库数据',
  `override_reason`    VARCHAR(512) DEFAULT NULL,
  `replaces_batch_id`  VARCHAR(40)  DEFAULT NULL COMMENT '被本次覆盖的上一批次',
  `operator`           VARCHAR(64)  DEFAULT NULL,
  `message`            VARCHAR(1000) DEFAULT NULL,
  `created_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `completed_at`       DATETIME     DEFAULT NULL,
  PRIMARY KEY (`batch_id`),
  UNIQUE KEY `uk_idempotency` (`idempotency_key`),
  KEY `idx_org_created` (`org_id`,`created_at`),
  KEY `idx_period` (`period_start`,`period_end`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='数据接入批次与幂等控制';

CREATE TABLE IF NOT EXISTS prediction_monthly_source_head (
  org_id VARCHAR(16) NOT NULL,
  period DATE NOT NULL,
  source_version BIGINT NOT NULL DEFAULT 0,
  awaiting_source TINYINT(1) NOT NULL DEFAULT 0,
  batch_id VARCHAR(40),
  PRIMARY KEY (org_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prediction_monthly_source_receipt (
  idempotency_key VARCHAR(64) NOT NULL,
  org_id VARCHAR(16) NOT NULL,
  period DATE NOT NULL,
  source_version BIGINT NOT NULL,
  request_hash CHAR(64) NOT NULL,
  payload JSON NOT NULL,
  response JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (idempotency_key),
  UNIQUE KEY uk_prediction_source_version (org_id, period, source_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- 8.1 入库覆盖审计（覆盖前保存旧值）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_ingest_audit` (
  `id`                BIGINT       NOT NULL AUTO_INCREMENT,
  `batch_id`          VARCHAR(40)  NOT NULL,
  `replaces_batch_id` VARCHAR(40)  DEFAULT NULL,
  `org_id`            VARCHAR(16)  NOT NULL,
  `period`            DATE         NOT NULL,
  `entity_type`       VARCHAR(16)  NOT NULL COMMENT 'activity/emission/anomaly',
  `entity_key`        VARCHAR(96)  NOT NULL,
  `var_id`            VARCHAR(32)  DEFAULT NULL,
  `old_value`         DECIMAL(20,6) DEFAULT NULL,
  `new_value`         DECIMAL(20,6) DEFAULT NULL,
  `old_status`        VARCHAR(32)  DEFAULT NULL,
  `new_status`        VARCHAR(32)  DEFAULT NULL,
  `detail`            JSON         DEFAULT NULL,
  `operator`          VARCHAR(64)  DEFAULT NULL,
  `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_batch` (`batch_id`),
  KEY `idx_org_period` (`org_id`,`period`),
  KEY `idx_entity` (`entity_type`,`entity_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='入库覆盖审计（活动/排放/异常旧值）';

-- ---------------------------------------------------------------------
-- 9. 数据集版本表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_dataset_version` (
  `version_id`    VARCHAR(40)  NOT NULL,
  `org_id`        VARCHAR(16)  NOT NULL,
  `start_period`  DATE         NOT NULL,
  `end_period`    DATE         NOT NULL,
  `row_count`     INT          NOT NULL,
  `content_hash`  VARCHAR(64)  NOT NULL,
  `note`          VARCHAR(512) DEFAULT NULL,
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`version_id`),
  KEY `idx_org_end` (`org_id`,`end_period`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='训练数据集版本与内容指纹';

-- ---------------------------------------------------------------------
-- 10. 灰色关联分析结果表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_gra_result` (
  `id`             BIGINT       NOT NULL AUTO_INCREMENT,
  `run_id`         VARCHAR(40)  NOT NULL,
  `org_id`         VARCHAR(16)  NOT NULL,
  `var_id`         VARCHAR(48)  NOT NULL,
  `var_name`       VARCHAR(64)  NOT NULL,
  `r`              DECIMAL(10,6) NOT NULL COMMENT '水平序列关联度',
  `r_detrend`      DECIMAL(10,6) DEFAULT NULL COMMENT '一阶差分后关联度',
  `rank_no`        INT          NOT NULL,
  `selected`       TINYINT(1)   NOT NULL DEFAULT 0,
  `spurious`       TINYINT(1)   NOT NULL DEFAULT 0,
  `rho_sensitive`  TINYINT(1)   NOT NULL DEFAULT 0,
  `borderline`     TINYINT(1)   NOT NULL DEFAULT 0,
  `direction`      VARCHAR(16)  DEFAULT 'unknown',
  `note`           VARCHAR(512) DEFAULT NULL,
  `created_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_run_org_var` (`run_id`,`org_id`,`var_id`),
  KEY `idx_org_run` (`org_id`,`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='灰色关联分析结果（关联度非因果）';

-- ---------------------------------------------------------------------
-- 11. 模型注册表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_model` (
  `model_id`        VARCHAR(64)  NOT NULL,
  `org_id`          VARCHAR(16)  NOT NULL,
  `model_type`      VARCHAR(32)  NOT NULL COMMENT 'SW_LSTM/RIDGE/GBM/HOLT_WINTERS/SEASONAL_NAIVE/ENSEMBLE',
  `version`         VARCHAR(16)  NOT NULL,
  `status`          VARCHAR(16)  NOT NULL DEFAULT 'candidate' COMMENT 'candidate/active/deprecated',
  `is_champion`     TINYINT(1)   NOT NULL DEFAULT 0,
  `target_var`      VARCHAR(32)  NOT NULL DEFAULT 'CO2_COMPARABLE',
  `window_size`     INT          NOT NULL,
  `horizon`         INT          NOT NULL,
  `feature_order`   JSON         NOT NULL,
  `hyperparams`     JSON         NOT NULL,
  `scaler_state`    JSON         NOT NULL,
  `metrics`         JSON         NOT NULL,
  `train_start`     DATE         NOT NULL,
  `train_end`       DATE         NOT NULL,
  `n_samples`       INT          NOT NULL,
  `artifact_path`   VARCHAR(512) NOT NULL,
  `data_version`    VARCHAR(40)  DEFAULT NULL,
  `trained_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `trained_by`      VARCHAR(64)  DEFAULT NULL,
  PRIMARY KEY (`model_id`),
  KEY `idx_org_status` (`org_id`,`status`),
  KEY `idx_champion` (`org_id`,`is_champion`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='模型注册表（多版本并存，冠军模型唯一）';

-- ---------------------------------------------------------------------
-- 12. 预测结果表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_forecast` (
  `id`               BIGINT       NOT NULL AUTO_INCREMENT,
  `model_id`         VARCHAR(64)  NOT NULL,
  `org_id`           VARCHAR(16)  NOT NULL,
  `period`           DATE         NOT NULL,
  `scenario`         VARCHAR(32)  NOT NULL DEFAULT 'BAU',
  `target_var`       VARCHAR(32)  NOT NULL DEFAULT 'CO2_COMPARABLE',
  `point`            DECIMAL(20,6) NOT NULL COMMENT '可比口径点预测',
  `lower_bound`      DECIMAL(20,6) DEFAULT NULL,
  `upper_bound`      DECIMAL(20,6) DEFAULT NULL,
  `reported_point`   DECIMAL(20,6) DEFAULT NULL COMMENT '折算到报表口径',
  `comparable_point` DECIMAL(20,6) DEFAULT NULL,
  `confidence_level` DECIMAL(4,2) NOT NULL DEFAULT 0.90,
  `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_model_org_period_scenario` (`model_id`,`org_id`,`period`,`scenario`,`target_var`),
  KEY `idx_org_period` (`org_id`,`period`,`scenario`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='未来一年预测结果（多模型/多情景并存）';

-- ---------------------------------------------------------------------
-- 13. 政策与外部因子事实表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_policy_factor` (
  `id`             BIGINT       NOT NULL AUTO_INCREMENT,
  `factor_id`      VARCHAR(48)  NOT NULL COMMENT 'COAL_PRICE_QHD5500 等',
  `factor_name`    VARCHAR(64)  NOT NULL,
  `period`         DATE         NOT NULL,
  `value`          DECIMAL(20,6) DEFAULT NULL,
  `unit`           VARCHAR(32)  NOT NULL,
  `category`       VARCHAR(32)  NOT NULL COMMENT 'price/supply/transport/power/weather/policy',
  `source_level`   VARCHAR(16)  NOT NULL DEFAULT 'national' COMMENT 'national/provincial/market/enterprise',
  `source_status`  VARCHAR(32)  NOT NULL DEFAULT '原始' COMMENT '原始/插值/1-2月合计均分/外推',
  `is_scenario_only` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=仅作情景输入，不进入常规特征',
  `data_source`    VARCHAR(512) DEFAULT NULL,
  `created_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_factor_period` (`factor_id`,`period`),
  KEY `idx_period` (`period`),
  KEY `idx_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='政策与外部因子月度事实表';

-- ---------------------------------------------------------------------
-- 14. 政策事件表（定性政策的结构化记录）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_policy_event` (
  `id`            BIGINT       NOT NULL AUTO_INCREMENT,
  `event_id`      VARCHAR(48)  NOT NULL,
  `event_name`    VARCHAR(128) NOT NULL,
  `start_period`  DATE         NOT NULL,
  `end_period`    DATE         DEFAULT NULL,
  `dimension`     VARCHAR(32)  NOT NULL COMMENT 'price/supply/transport/grid/carbon_market',
  `description`   VARCHAR(1000) DEFAULT NULL,
  `source_url`    VARCHAR(512) DEFAULT NULL,
  `intensity`     DECIMAL(6,4) DEFAULT NULL COMMENT '0-1 专家强度评分，仅用于情景，不进入GRA',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_event` (`event_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='政策事件时间线（定性政策的可追溯记录）';

-- ---------------------------------------------------------------------
-- 15. 情景定义表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_scenario` (
  `scenario_id`   VARCHAR(32)  NOT NULL,
  `scenario_name` VARCHAR(64)  NOT NULL,
  `description`   VARCHAR(512) DEFAULT NULL,
  `config`        JSON         NOT NULL,
  `is_default`    TINYINT(1)   NOT NULL DEFAULT 0,
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`scenario_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='预测情景定义';

-- ---------------------------------------------------------------------
-- 16. 异步任务表
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_job` (
  `job_id`      VARCHAR(40)  NOT NULL,
  `job_type`    VARCHAR(32)  NOT NULL COMMENT 'TRAIN/FORECAST/GRA/IMPORT',
  `status`      VARCHAR(16)  NOT NULL DEFAULT 'queued' COMMENT 'queued/running/succeeded/failed',
  `params`      JSON         DEFAULT NULL,
  `result`      JSON         DEFAULT NULL,
  `error`       VARCHAR(1000) DEFAULT NULL,
  `operator`    VARCHAR(64)  DEFAULT NULL,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `started_at`  DATETIME     DEFAULT NULL,
  `finished_at` DATETIME     DEFAULT NULL,
  PRIMARY KEY (`job_id`),
  KEY `idx_status` (`status`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='训练/预测异步任务';

-- ---------------------------------------------------------------------
-- 17. 审计日志
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prediction_audit_log` (
  `id`          BIGINT       NOT NULL AUTO_INCREMENT,
  `action`      VARCHAR(64)  NOT NULL,
  `entity`      VARCHAR(64)  NOT NULL,
  `entity_id`   VARCHAR(64)  DEFAULT NULL,
  `operator`    VARCHAR(64)  DEFAULT NULL,
  `detail`      JSON         DEFAULT NULL,
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_entity` (`entity`,`entity_id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='模块审计日志';

-- ---------------------------------------------------------------------
-- 18. 宽表视图（供平台展示层直接查询）
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS `prediction_v_carbon_monthly`;
CREATE VIEW `prediction_v_carbon_monthly` AS
SELECT
  a.`org_id`,
  o.`org_name`,
  a.`period`,
  MAX(CASE WHEN a.`var_id`='TURNOVER'     THEN a.`value` END) AS `turnover`,
  MAX(CASE WHEN a.`var_id`='GAS'          THEN a.`value` END) AS `gas`,
  MAX(CASE WHEN a.`var_id`='GASOLINE'     THEN a.`value` END) AS `gasoline`,
  MAX(CASE WHEN a.`var_id`='DIESEL'       THEN a.`value` END) AS `diesel`,
  MAX(CASE WHEN a.`var_id`='ELEC_TOTAL'   THEN a.`value` END) AS `electricity_total`,
  MAX(CASE WHEN a.`var_id`='ELEC_TRAC'    THEN a.`value` END) AS `electricity_traction`,
  MAX(CASE WHEN a.`var_id`='ELEC_AUX'     THEN a.`value` END) AS `electricity_aux`,
  MAX(CASE WHEN a.`var_id`='HEAT'         THEN a.`value` END) AS `heat_gj`,
  MAX(CASE WHEN a.`var_id`='HEAT_REPORTED' THEN a.`reported_value` END) AS `heat_reported_gj`,
  MAX(e.`total_reported_tco2`)   AS `co2_reported_tco2`,
  MAX(e.`total_comparable_tco2`) AS `co2_comparable_tco2`,
  MAX(e.`is_verified`)           AS `is_verified`
FROM `prediction_activity_monthly` a
JOIN `prediction_org` o ON o.`org_id`=a.`org_id`
LEFT JOIN `prediction_emission_monthly` e
  ON e.`org_id`=a.`org_id` AND e.`period`=a.`period` AND e.`scope`='Total'
WHERE a.`quality_status` <> 'excluded'
GROUP BY a.`org_id`, o.`org_name`, a.`period`;
