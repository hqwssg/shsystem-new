package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.ScopeCompletenessResult;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScopeBaseline;

import java.math.BigDecimal;
import java.util.List;

/**
 * Scope 级完整性分量 Service（规范 5.13）
 * <p>
 * 负责按 Scope 计算完整性判据（benchmark_measured/measured/disabled）、
 * r_benchmark/r_measured、delta_cov_percent 分段、E[ξ_cov] 及强制披露文案，
 * 并提供 I6 独立基准的 upsert 能力。
 */
public interface ScopeCompletenessService {

    /**
     * 计算核算任务下全部 Scope 的完整性分量
     *
     * @param calculationTemplateId 核算任务ID
     * @param ruleset               规则库版本（提供 coverage_delta_cap 与 coverage_alpha）
     * @return 每个 Scope 一条评估结果
     */
    List<ScopeCompletenessResult> compute(Long calculationTemplateId, UncertaintyRuleset ruleset);

    /**
     * 新增或更新某 Scope 的 I6 独立基准（按 calculationTemplateId+scope upsert）
     *
     * @param calculationTemplateId 核算任务ID
     * @param scope                 Scope类别
     * @param benchmarkQty          独立基准量（必须为正，否则抛 IllegalArgumentException）
     * @param unit                  基准量单位
     * @param source                基准来源
     */
    void saveBaseline(Long calculationTemplateId, String scope, BigDecimal benchmarkQty, String unit, String source);

    /**
     * 查询核算任务下全部 Scope 独立基准列表（I6）
     *
     * @param calculationTemplateId 核算任务ID
     * @return 基准列表
     */
    List<UncertaintyScopeBaseline> listBaselines(Long calculationTemplateId);
}
