package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * DQI 评分实体类（I2，每参数每维度一行）
 * <p>
 * 对应表 uncertainty_score，存储排放源元信息每个参数类型
 * （AD/EF）下各维度的建议分、最终分、分值来源及人工覆盖信息。
 */
@Entity
@Table(name = "uncertainty_score")
@Data
public class UncertaintyScore {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 排放源元信息ID，关联 uncertainty_source_meta.id
     */
    @Column(name = "source_meta_id", nullable = false)
    private Long sourceMetaId;

    /**
     * 参数类型：AD / EF
     */
    @Column(name = "param_type", nullable = false, length = 10)
    private String paramType;

    /**
     * 维度编号
     */
    @Column(name = "dim_code", nullable = false, length = 10)
    private String dimCode;

    /**
     * 评分时使用的维度权重（快照）
     */
    @Column(name = "weight", nullable = false,
            columnDefinition = "DECIMAL(6,3) NOT NULL DEFAULT 1.0")
    private BigDecimal weight = BigDecimal.ONE;

    /**
     * M2a建议分（缺失转人工时为NULL，禁止默认填充）
     */
    @Column(name = "suggested_score")
    private Integer suggestedScore;

    /**
     * 判定依据（驱动字段取值+命中区间）
     */
    @Column(name = "score_evidence", length = 1000)
    private String scoreEvidence;

    /**
     * 自动评分状态：complete/partial/unavailable
     */
    @Column(name = "auto_scoring_status", length = 20)
    private String autoScoringStatus = "complete";

    /**
     * 最终分（1-5整数，人工确认/覆盖后必填）
     */
    @Column(name = "final_score")
    private Integer finalScore;

    /**
     * 分值来源：auto/manual_override/expert_override/neutral/auto_neutral_excluded
     */
    @Column(name = "score_source", length = 30)
    private String scoreSource;

    /**
     * 人工覆盖理由（score_source=manual_override时必填）
     */
    @Column(name = "override_reason", length = 1000)
    private String overrideReason;

    /**
     * A6来源标记：normal/neutral_excluded（仅A6维度使用）
     */
    @Column(name = "a6_source", length = 30)
    private String a6Source;

    /**
     * ad_geo_basis留空被默认填充标记
     */
    @Column(name = "default_filled", nullable = false,
            columnDefinition = "TINYINT(1) NOT NULL DEFAULT 0")
    private Integer defaultFilled = 0;

    /**
     * 该维度触发的警告编号（逗号分隔）
     */
    @Column(name = "warnings", length = 500)
    private String warnings;

    /**
     * 评分所用规则库版本（永久绑定）
     */
    @Column(name = "ruleset_version", nullable = false, length = 50)
    private String rulesetVersion;

    /**
     * 复核人
     */
    @Column(name = "reviewer", length = 100)
    private String reviewer;

    /**
     * 复核时间
     */
    @Column(name = "review_time")
    private LocalDateTime reviewTime;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    /**
     * 更新时间
     */
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
        if (weight == null) {
            weight = BigDecimal.ONE;
        }
        if (autoScoringStatus == null) {
            autoScoringStatus = "complete";
        }
        if (defaultFilled == null) {
            defaultFilled = 0;
        }
    }
}
