package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * DQI 规则库维度规则实体类
 * <p>
 * 对应表 uncertainty_dimension_rule，存储规则库中每个参数类型
 * （AD/EF）下各维度的评分规则，包括 mapping/band/direct_score 三种规则
 * 类型、缺失策略及 band 有效域等。
 */
@Entity
@Table(name = "uncertainty_dimension_rule")
@Data
public class UncertaintyDimensionRule {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 规则库ID，关联 uncertainty_ruleset.id
     */
    @Column(name = "ruleset_id", nullable = false)
    private Long rulesetId;

    /**
     * 适用参数类型：AD / EF（单值）
     */
    @Column(name = "applies_to", nullable = false, length = 10)
    private String appliesTo;

    /**
     * 维度编号：AD 用 A1/A2/A4/A5/A6，EF 用 E1-E6
     */
    @Column(name = "dim_code", nullable = false, length = 10)
    private String dimCode;

    /**
     * 维度中文名称
     */
    @Column(name = "dim_name", nullable = false, length = 100)
    private String dimName;

    /**
     * 是否启用：1-是，0-否（停用后∑Qmin/∑Qmax自动重算）
     */
    @Column(name = "enabled", nullable = false,
            columnDefinition = "TINYINT(1) NOT NULL DEFAULT 1")
    private Integer enabled = 1;

    /**
     * 维度权重，须≥0，=0等效禁用该维度
     */
    @Column(name = "weight", nullable = false,
            columnDefinition = "DECIMAL(6,3) NOT NULL DEFAULT 1.0")
    private BigDecimal weight = BigDecimal.ONE;

    /**
     * 驱动字段名或派生量名（如 ad_metering_tier / delta_year）
     */
    @Column(name = "driver", nullable = false, length = 64)
    private String driver;

    /**
     * 规则类型：mapping-枚举查表 / band-数值分段 / direct_score-直接评分
     */
    @Column(name = "rule_type", nullable = false, length = 20)
    private String ruleType;

    /**
     * mapping:{枚举值:分值}；band:[[下界(含),上界(不含),分值],...]；direct_score 为空
     */
    @Column(name = "entries", columnDefinition = "json")
    private String entries;

    /**
     * 缺失策略：to_manual / default_with_flag / neutral
     */
    @Column(name = "null_policy", nullable = false, length = 30)
    private String nullPolicy = "to_manual";

    /**
     * 中性分值（null_policy=neutral 时必填，如 A2 不适用取3）
     */
    @Column(name = "neutral_score")
    private Integer neutralScore;

    /**
     * 触发中性分的枚举取值（如 calib_not_applicable）
     */
    @Column(name = "neutral_when_value", length = 64)
    private String neutralWhenValue;

    /**
     * 默认填充值（null_policy=default_with_flag 时必填，如 direct_metered）
     */
    @Column(name = "default_value", length = 64)
    private String defaultValue;

    /**
     * 默认填充时是否标注 default_filled=true
     */
    @Column(name = "mark_default_filled", nullable = false,
            columnDefinition = "TINYINT(1) NOT NULL DEFAULT 0")
    private Integer markDefaultFilled = 0;

    /**
     * band 有效域 [下界,上界]，超出视为越域转人工（不构成加载失败）
     */
    @Column(name = "valid_range", columnDefinition = "json")
    private String validRange;

    /**
     * 越域警告文本
     */
    @Column(name = "out_of_range_warning", length = 500)
    private String outOfRangeWarning;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        if (enabled == null) {
            enabled = 1;
        }
        if (weight == null) {
            weight = BigDecimal.ONE;
        }
        if (nullPolicy == null) {
            nullPolicy = "to_manual";
        }
        if (markDefaultFilled == null) {
            markDefaultFilled = 0;
        }
    }
}
