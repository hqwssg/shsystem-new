package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 不确定性分析报告 DTO（O5）
 * <p>
 * 按 runId 聚合单次模拟运行的全部落库输出，面向前端渲染与 PDF 导出，
 * 章节：任务信息与配置快照、点估计与上抬、MCS 统计量与置信区间、
 * 无偏性验证与不确定性等级（O4）、Scope 级完整性披露（O7）、
 * 参数级归一化与分布参数明细（O1）、警告集合。
 */
@Data
public class UncertaintyReportDto {

    /**
     * 报告生成时间
     */
    private LocalDateTime generatedAt;

    /**
     * 任务信息与配置快照
     */
    private TaskInfoSection taskInfo;

    /**
     * 点估计与上抬
     */
    private PointEstimateSection pointEstimate;

    /**
     * MCS 统计量与置信区间
     */
    private McsStatisticsSection mcsStatistics;

    /**
     * 无偏性验证与不确定性等级（O4）
     */
    private VerificationSection verification;

    /**
     * Scope 级完整性披露（O7）
     */
    private List<ScopeCompletenessSection> scopeCompleteness;

    /**
     * 参数级归一化与分布参数明细（O1）
     */
    private List<ParamDetailSection> paramDetails;

    /**
     * 本次运行触发的警告集合
     */
    private List<String> warnings;

    /**
     * 任务信息与配置快照章节
     */
    @Data
    public static class TaskInfoSection {
        /** 模拟运行ID */
        private Long runId;
        /** 核算任务ID */
        private Long calculationTemplateId;
        /** 运行状态：RUNNING/SUCCESS/FAILED */
        private String status;
        /** 本次运行使用的规则库版本 */
        private String rulesetVersion;
        /** MCS迭代次数 */
        @JsonProperty("nIterations")
        private Integer nIterations;
        /** 置信水平 */
        private BigDecimal confidenceLevel;
        /** 随机种子（固定可复现） */
        private Long randomSeed;
        /** 完整性作用范围 */
        private String completenessScopeLevel;
        /** 开始时间 */
        private LocalDateTime startedAt;
        /** 完成时间 */
        private LocalDateTime finishedAt;
    }

    /**
     * 点估计与上抬章节
     */
    @Data
    public static class PointEstimateSection {
        /** 记录下锚点估计：ΣE_i（无完整性修正） */
        @JsonProperty("ePointRaw")
        private BigDecimal ePointRaw;
        /** 完整性修正后点估计：Σ_g(E[g]×E[ξ_cov(g)]) */
        @JsonProperty("ePointCov")
        private BigDecimal ePointCov;
        /** 上抬百分比：(E_point_cov-E_point_raw)/E_point_raw×100% */
        private BigDecimal upliftPercent;
    }

    /**
     * MCS 统计量与置信区间章节
     */
    @Data
    public static class McsStatisticsSection {
        /** MCS样本均值μ_E */
        private BigDecimal totalMean;
        /** MCS样本中位数 */
        private BigDecimal totalMedian;
        /** MCS样本标准差σ_E */
        private BigDecimal totalStd;
        /** 变异系数CV=σ_E/μ_E×100% */
        private BigDecimal cvPercent;
        /** 置信区间下界（分位数法） */
        private BigDecimal ciLower;
        /** 置信区间上界 */
        private BigDecimal ciUpper;
        /** 分位数集合 {p5,p25,p50,p75,p95} */
        private Map<String, Double> quantiles;
    }

    /**
     * 无偏性验证与不确定性等级章节（O4）
     */
    @Data
    public static class VerificationSection {
        /** 均值偏差：(μ_E-E_point_cov)/E_point_cov×100%，|≤2%|为无偏 */
        private BigDecimal devMeanPercent;
        /** 中位数偏差（|≤5%|） */
        private BigDecimal devMedianPercent;
        /** E_point_cov是否落入置信区间 */
        private Boolean pointCovInCi;
        /** 下锚关系：E_point_raw≤E_point_cov */
        private Boolean rawLeCov;
        /** 不确定性等级：低/中/较高/高（按CV分级） */
        private String uncertaintyLevel;
        /** 验证结论文本（O4） */
        private String verificationConclusion;
    }

    /**
     * Scope 级完整性披露章节行（O7）
     */
    @Data
    public static class ScopeCompletenessSection {
        /** Scope类别 */
        private String scope;
        /** 该Scope记录级排放量小计E[g] */
        private BigDecimal scopeEmission;
        /** 判据类型：benchmark_measured/measured/disabled */
        private String basis;
        /** 独立基准量（无基准为NULL） */
        private BigDecimal benchmarkQty;
        /** 基准来源 */
        private String benchmarkSource;
        /** 规模完整性：ΣAD_i/benchmark_qty */
        @JsonProperty("rBenchmark")
        private BigDecimal rBenchmark;
        /** 排放量加权计量支撑度 */
        @JsonProperty("rMeasured")
        private BigDecimal rMeasured;
        /** 点数比x/n（仅诊断，不参与定价） */
        private BigDecimal pointRatioXn;
        /** Scope级δ_cov */
        private BigDecimal deltaCovPercent;
        /** E[ξ_cov]=1+(δ_cov/100)/16 */
        @JsonProperty("eXiCov")
        private BigDecimal eXiCov;
        /** basis=disabled时的强制披露文案 */
        private String disclosure;
    }

    /**
     * 参数级归一化与分布参数明细章节行（O1）
     */
    @Data
    public static class ParamDetailSection {
        /** 排放源元信息ID */
        private Long sourceMetaId;
        /** 排放源名称（关联 uncertainty_source_meta 展示用） */
        private String sourceName;
        /** 参数类型：AD / EF */
        private String paramType;
        /** 规则库版本 */
        private String rulesetVersion;
        /** 加权总分∑Q_w */
        private BigDecimal sumQW;
        /** 归一化下界∑Qmin_w */
        private BigDecimal sumQMinW;
        /** 归一化上界∑Qmax_w */
        private BigDecimal sumQMaxW;
        /** 归一化质量分数x(%) */
        @JsonProperty("xPercent")
        private BigDecimal xPercent;
        /** SDQI（1.0-5.0步进0.5） */
        private BigDecimal sdqi;
        /** Beta分布形状参数α=SDQI² */
        private BigDecimal betaAlpha;
        /** Beta分布形状参数β=SDQI² */
        private BigDecimal betaBeta;
        /** 支撑半宽δ（名义值%） */
        private BigDecimal deltaPercent;
        /** 支撑区间下因子1-δ/100 */
        private BigDecimal supportLowFactor;
        /** 支撑区间上因子1+δ/100 */
        private BigDecimal supportHighFactor;
        /** 该参数触发的警告编号 */
        private String warnings;
    }
}
