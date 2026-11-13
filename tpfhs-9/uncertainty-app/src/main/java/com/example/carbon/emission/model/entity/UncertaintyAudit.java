package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * DQI 评分变更审计实体类（O6）
 * <p>
 * 对应表 uncertainty_audit，记录评分的人工变更留痕，
 * 包括改前/改后分值、分值来源、覆盖理由及复核信息。
 */
@Entity
@Table(name = "uncertainty_audit")
@Data
public class UncertaintyAudit {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 评分记录ID，关联 uncertainty_score.id
     */
    @Column(name = "score_id", nullable = false)
    private Long scoreId;

    /**
     * 排放源元信息ID（冗余，便于按源查询）
     */
    @Column(name = "source_meta_id", nullable = false)
    private Long sourceMetaId;

    /**
     * 参数类型
     */
    @Column(name = "param_type", nullable = false, length = 10)
    private String paramType;

    /**
     * 维度编号
     */
    @Column(name = "dim_code", nullable = false, length = 10)
    private String dimCode;

    /**
     * 改前最终分
     */
    @Column(name = "old_score")
    private Integer oldScore;

    /**
     * 改后最终分
     */
    @Column(name = "new_score")
    private Integer newScore;

    /**
     * 改前分值来源
     */
    @Column(name = "old_source", length = 30)
    private String oldSource;

    /**
     * 改后分值来源
     */
    @Column(name = "new_source", length = 30)
    private String newSource;

    /**
     * 覆盖理由
     */
    @Column(name = "override_reason", length = 1000)
    private String overrideReason;

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
     * 规则库版本
     */
    @Column(name = "ruleset_version", length = 50)
    private String rulesetVersion;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
