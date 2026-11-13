package com.example.carbon.emission.model.entity;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.*;
import lombok.Data;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 不确定性分析模拟运行实体类
 * <p>
 * 对应表 uncertainty_run，存储一次蒙特卡洛模拟（MCS）运行的
 * 参数配置与汇总结果（M3-M5），包括点估计、统计量、置信区间、
 * 无偏性验证与下锚关系（O2/O3/O4）。
 */
@Entity
@Table(name = "uncertainty_run")
@Data
public class UncertaintyRun {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 核算任务ID，逻辑关联 emission_calculation_template.id
     */
    @Column(name = "calculation_template_id", nullable = false)
    private Long calculationTemplateId;

    /**
     * 本次运行使用的规则库版本
     */
    @Column(name = "ruleset_version", nullable = false, length = 50)
    private String rulesetVersion;

    /**
     * MCS迭代次数（1000-1000000）
     */
    @Column(name = "n_iterations", nullable = false)
    @JsonProperty("nIterations")
    private Integer nIterations = 10000;

    /**
     * 置信水平
     */
    @Column(name = "confidence_level", nullable = false,
            columnDefinition = "DECIMAL(4,3) NOT NULL DEFAULT 0.950")
    private BigDecimal confidenceLevel = new BigDecimal("0.950");

    /**
     * 随机种子（固定可复现）
     */
    @Column(name = "random_seed")
    private Long randomSeed;

    /**
     * 完整性作用范围：boundary/scope/category
     */
    @Column(name = "completeness_scope_level", nullable = false, length = 20)
    private String completenessScopeLevel = "scope";

    /**
     * 运行状态：RUNNING/SUCCESS/FAILED
     */
    @Column(name = "status", nullable = false, length = 20)
    private String status = "RUNNING";

    /**
     * 失败原因
     */
    @Column(name = "error_message", columnDefinition = "text")
    private String errorMessage;

    /**
     * 记录下锚点估计：ΣE_i（无完整性修正）
     */
    @Column(name = "e_point_raw", columnDefinition = "DECIMAL(28,8)")
    @JsonProperty("ePointRaw")
    private BigDecimal ePointRaw;

    /**
     * 完整性修正后点估计：Σ_g(E[g]×E[ξ_cov(g)])，验证基准
     */
    @Column(name = "e_point_cov", columnDefinition = "DECIMAL(28,8)")
    @JsonProperty("ePointCov")
    private BigDecimal ePointCov;

    /**
     * 上抬百分比：(E_point_cov-E_point_raw)/E_point_raw×100%
     */
    @Column(name = "uplift_percent", columnDefinition = "DECIMAL(10,4)")
    private BigDecimal upliftPercent;

    /**
     * MCS样本均值μ_E
     */
    @Column(name = "total_mean", columnDefinition = "DECIMAL(28,8)")
    private BigDecimal totalMean;

    /**
     * MCS样本中位数
     */
    @Column(name = "total_median", columnDefinition = "DECIMAL(28,8)")
    private BigDecimal totalMedian;

    /**
     * MCS样本标准差σ_E
     */
    @Column(name = "total_std", columnDefinition = "DECIMAL(28,8)")
    private BigDecimal totalStd;

    /**
     * 变异系数CV=σ_E/μ_E×100%
     */
    @Column(name = "cv_percent", columnDefinition = "DECIMAL(10,4)")
    private BigDecimal cvPercent;

    /**
     * 置信区间下界（分位数法）
     */
    @Column(name = "ci_lower", columnDefinition = "DECIMAL(28,8)")
    private BigDecimal ciLower;

    /**
     * 置信区间上界
     */
    @Column(name = "ci_upper", columnDefinition = "DECIMAL(28,8)")
    private BigDecimal ciUpper;

    /**
     * 分位数集合 {p5,p25,p50,p75,p95}
     */
    @Column(name = "quantiles", columnDefinition = "json")
    private String quantiles;

    /**
     * 均值偏差：(μ_E-E_point_cov)/E_point_cov×100%，|≤2%|为无偏
     */
    @Column(name = "dev_mean_percent", columnDefinition = "DECIMAL(10,4)")
    private BigDecimal devMeanPercent;

    /**
     * 中位数偏差（|≤5%|）
     */
    @Column(name = "dev_median_percent", columnDefinition = "DECIMAL(10,4)")
    private BigDecimal devMedianPercent;

    /**
     * E_point_cov是否落入置信区间
     */
    @Column(name = "point_cov_in_ci")
    @JdbcTypeCode(SqlTypes.TINYINT)
    private Boolean pointCovInCi;

    /**
     * 下锚关系：E_point_raw≤E_point_cov
     */
    @Column(name = "raw_le_cov")
    @JdbcTypeCode(SqlTypes.TINYINT)
    private Boolean rawLeCov;

    /**
     * 不确定性等级：低/中/较高/高（按CV分级）
     */
    @Column(name = "uncertainty_level", length = 10)
    private String uncertaintyLevel;

    /**
     * 验证结论文本（O4）
     */
    @Column(name = "verification_conclusion", columnDefinition = "text")
    private String verificationConclusion;

    /**
     * 本次运行触发的警告编号及内容集合
     */
    @Column(name = "warnings", columnDefinition = "json")
    private String warnings;

    /**
     * 开始时间
     */
    @Column(name = "started_at")
    private LocalDateTime startedAt;

    /**
     * 完成时间
     */
    @Column(name = "finished_at")
    private LocalDateTime finishedAt;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        if (nIterations == null) {
            nIterations = 10000;
        }
        if (confidenceLevel == null) {
            confidenceLevel = new BigDecimal("0.950");
        }
        if (completenessScopeLevel == null) {
            completenessScopeLevel = "scope";
        }
        if (status == null) {
            status = "RUNNING";
        }
    }
}
