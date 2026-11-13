package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * DQI 规则库版本实体类
 * <p>
 * 对应表 uncertainty_ruleset，存储不确定性分析（DQI+MCS）模块的
 * 规则库版本信息，包括维度权重、δ表、标定信息及 Scope 级完整性封顶参数。
 */
@Entity
@Table(name = "uncertainty_ruleset")
@Data
public class UncertaintyRuleset {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 规则库版本号，如 DQI-RULES-2026.12
     */
    @Column(name = "ruleset_version", nullable = false, length = 50)
    private String rulesetVersion;

    /**
     * 生效日期
     */
    @Column(name = "effective_date")
    private LocalDate effectiveDate;

    /**
     * 规则库审核人
     */
    @Column(name = "reviewer", length = 100)
    private String reviewer;

    /**
     * 按 param_type 的维度权重：{"AD":{"A1":1.0,...},"EF":{"E1":1.0,...}}
     */
    @Column(name = "dimension_weights", columnDefinition = "json")
    private String dimensionWeights;

    /**
     * δ表实证标定信息（来源/样本量/日期/对照结论），未标定则报告强制声明
     */
    @Column(name = "calibration_meta", columnDefinition = "json")
    private String calibrationMeta;

    /**
     * SDQI→支撑半宽δ映射表
     */
    @Column(name = "delta_table", columnDefinition = "json")
    private String deltaTable;

    /**
     * Scope级 delta_cov_percent 封顶值（%）
     */
    @Column(name = "coverage_delta_cap", nullable = false,
            columnDefinition = "DECIMAL(5,2) NOT NULL DEFAULT 30")
    private BigDecimal coverageDeltaCap = new BigDecimal("30");

    /**
     * Scope级单侧因子 ξ_cov 的 Beta 参数 α_cov（固定15，Beta(1,α_cov)）
     */
    @Column(name = "coverage_alpha", nullable = false,
            columnDefinition = "DECIMAL(6,2) NOT NULL DEFAULT 15")
    private BigDecimal coverageAlpha = new BigDecimal("15");

    /**
     * 本次升版变更理由（权重/启用状态变更必须填写）
     */
    @Column(name = "change_reason", length = 500)
    private String changeReason;

    /**
     * 创建人
     */
    @Column(name = "created_by", length = 100)
    private String createdBy;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        if (coverageDeltaCap == null) {
            coverageDeltaCap = new BigDecimal("30");
        }
        if (coverageAlpha == null) {
            coverageAlpha = new BigDecimal("15");
        }
    }
}
