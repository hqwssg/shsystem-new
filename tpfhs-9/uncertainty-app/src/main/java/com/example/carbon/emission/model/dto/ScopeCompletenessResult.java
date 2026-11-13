package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Scope 级完整性评估结果 DTO（规范 5.13）
 * <p>
 * 承载单个 Scope 的完整性判据（benchmark_measured/measured/disabled）、
 * r_benchmark/r_measured、点数比 x/n（仅诊断）、delta_cov_percent、
 * E[ξ_cov] 及强制披露文案与警告集合。
 */
@Data
public class ScopeCompletenessResult {

    /**
     * Scope类别（空scope的源归入"未分组"）
     */
    private String scope;

    /**
     * 该Scope记录级排放量小计E[g]
     */
    private BigDecimal scopeEmission;

    /**
     * 判据类型：benchmark_measured/measured/disabled
     */
    private String basis;

    /**
     * 独立基准量（无基准为NULL）
     */
    private BigDecimal benchmarkQty;

    /**
     * 基准来源
     */
    private String benchmarkSource;

    /**
     * 规模完整性：ΣAD_i/benchmark_qty
     */
    @JsonProperty("rBenchmark")
    private BigDecimal rBenchmark;

    /**
     * 排放量加权计量支撑度r_measured
     */
    @JsonProperty("rMeasured")
    private BigDecimal rMeasured;

    /**
     * 点数比x/n（仅诊断，不参与计算）
     */
    private BigDecimal pointRatioXn;

    /**
     * Scope级δ_cov（由r_eff直接查分段表，封顶coverage_delta_cap）
     */
    private BigDecimal deltaCovPercent;

    /**
     * E[ξ_cov]=1+(δ_cov/100)/(α_cov+1)
     */
    @JsonProperty("eXiCov")
    private BigDecimal eXiCov;

    /**
     * basis=disabled时的强制披露文案
     */
    private String disclosure;

    /**
     * 本Scope触发的警告（含W15/W16/W17等编号及内容）
     */
    private List<String> warnings = new ArrayList<>();
}
