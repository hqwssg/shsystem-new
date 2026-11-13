package com.example.carbon.emission.model.entity;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 参数级归一化与 Beta 分布参数实体类（O1，每次运行每参数一行）
 * <p>
 * 对应表 uncertainty_param_result，存储一次模拟运行中每个参数
 * （AD/EF）的加权总分、归一化质量分数、SDQI 及 Beta 分布形状参数与
 * 支撑区间因子。
 */
@Entity
@Table(name = "uncertainty_param_result")
@Data
public class UncertaintyParamResult {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 模拟运行ID，关联 uncertainty_run.id
     */
    @Column(name = "run_id", nullable = false)
    private Long runId;

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
     * 规则库版本
     */
    @Column(name = "ruleset_version", nullable = false, length = 50)
    private String rulesetVersion;

    /**
     * 加权总分∑Q_w=Σ(w_j×s_j)
     */
    @Column(name = "sum_q_w", columnDefinition = "DECIMAL(10,3)")
    private BigDecimal sumQW;

    /**
     * 归一化下界∑Qmin_w
     */
    @Column(name = "sum_q_min_w", columnDefinition = "DECIMAL(10,3)")
    private BigDecimal sumQMinW;

    /**
     * 归一化上界∑Qmax_w
     */
    @Column(name = "sum_q_max_w", columnDefinition = "DECIMAL(10,3)")
    private BigDecimal sumQMaxW;

    /**
     * 归一化质量分数x(%)
     */
    @Column(name = "x_percent", columnDefinition = "DECIMAL(8,4)")
    @JsonProperty("xPercent")
    private BigDecimal xPercent;

    /**
     * SDQI（表4-4，1.0-5.0步进0.5）
     */
    @Column(name = "sdqi", columnDefinition = "DECIMAL(3,1)")
    private BigDecimal sdqi;

    /**
     * Beta分布形状参数α=SDQI²
     */
    @Column(name = "beta_alpha", columnDefinition = "DECIMAL(12,4)")
    private BigDecimal betaAlpha;

    /**
     * Beta分布形状参数β=SDQI²
     */
    @Column(name = "beta_beta", columnDefinition = "DECIMAL(12,4)")
    private BigDecimal betaBeta;

    /**
     * 支撑半宽δ（SDQI查δ表，名义值%）
     */
    @Column(name = "delta_percent", columnDefinition = "DECIMAL(8,4)")
    private BigDecimal deltaPercent;

    /**
     * 支撑区间下因子1-δ/100
     */
    @Column(name = "support_low_factor", columnDefinition = "DECIMAL(8,5)")
    private BigDecimal supportLowFactor;

    /**
     * 支撑区间上因子1+δ/100
     */
    @Column(name = "support_high_factor", columnDefinition = "DECIMAL(8,5)")
    private BigDecimal supportHighFactor;

    /**
     * 该参数触发的警告编号
     */
    @Column(name = "warnings", length = 500)
    private String warnings;

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
