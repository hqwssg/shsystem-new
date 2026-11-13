package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.ScopeCompletenessResult;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScopeBaseline;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.repository.UncertaintyScopeBaselineRepository;
import com.example.carbon.emission.model.repository.UncertaintySourceMetaRepository;
import com.example.carbon.emission.model.service.ScopeCompletenessService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Scope 级完整性分量 Service 实现（规范 5.13）
 */
@Service
@Transactional(readOnly = true)
public class ScopeCompletenessServiceImpl implements ScopeCompletenessService {

    private static final Logger log = LoggerFactory.getLogger(ScopeCompletenessServiceImpl.class);

    /**
     * 直采（直接采集）计量档位集合
     */
    private static final Set<String> DIRECT_TIERS = Set.of("online_meter", "manual_ledger");

    /**
     * 空scope源的默认分组名
     */
    private static final String UNGROUPED = "未分组";

    /**
     * 判据类型：有独立基准
     */
    private static final String BASIS_BENCHMARK_MEASURED = "benchmark_measured";

    /**
     * 判据类型：无基准但可区分直采/估算
     */
    private static final String BASIS_MEASURED = "measured";

    /**
     * 判据类型：无法评估（不施加遗漏修正）
     */
    private static final String BASIS_DISABLED = "disabled";

    /**
     * 数值计算统一保留小数位
     */
    private static final int SCALE = 6;

    /**
     * 排放源元信息 Repository
     */
    @Autowired
    private UncertaintySourceMetaRepository uncertaintySourceMetaRepository;

    /**
     * Scope 级完整性基准 Repository
     */
    @Autowired
    private UncertaintyScopeBaselineRepository uncertaintyScopeBaselineRepository;

    @Override
    public List<ScopeCompletenessResult> compute(Long calculationTemplateId, UncertaintyRuleset ruleset) {
        if (calculationTemplateId == null || ruleset == null) {
            log.warn("compute 调用失败：calculationTemplateId 或 ruleset 为 null");
            return new ArrayList<>();
        }

        // 步骤1：拉取该核算任务全部排放源，按 scope 分组（空 scope 归入"未分组"）
        List<UncertaintySourceMeta> sources = uncertaintySourceMetaRepository
                .findByCalculationTemplateId(calculationTemplateId);
        Map<String, List<UncertaintySourceMeta>> byScope = new LinkedHashMap<>();
        for (UncertaintySourceMeta source : sources) {
            byScope.computeIfAbsent(scopeKey(source.getScope()), k -> new ArrayList<>()).add(source);
        }

        // 步骤2：取规则库封顶参数（coverage_delta_cap 默认30，coverage_alpha 默认15）
        BigDecimal deltaCap = ruleset.getCoverageDeltaCap() != null
                ? ruleset.getCoverageDeltaCap() : new BigDecimal("30");
        BigDecimal coverageAlpha = ruleset.getCoverageAlpha() != null
                ? ruleset.getCoverageAlpha() : new BigDecimal("15");

        // 步骤3：逐 Scope 计算完整性分量
        List<ScopeCompletenessResult> results = new ArrayList<>();
        for (Map.Entry<String, List<UncertaintySourceMeta>> entry : byScope.entrySet()) {
            results.add(computeOneScope(calculationTemplateId, entry.getKey(), entry.getValue(),
                    deltaCap, coverageAlpha));
        }
        return results;
    }

    @Override
    @Transactional
    public void saveBaseline(Long calculationTemplateId, String scope, BigDecimal benchmarkQty,
                             String unit, String source) {
        if (calculationTemplateId == null || scope == null || scope.isBlank()) {
            throw new IllegalArgumentException("核算任务ID与Scope类别不能为空");
        }
        if (benchmarkQty == null || benchmarkQty.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("独立基准量 benchmark_qty 必须为正数");
        }

        Optional<UncertaintyScopeBaseline> existing = uncertaintyScopeBaselineRepository
                .findByCalculationTemplateIdAndScope(calculationTemplateId, scope);
        UncertaintyScopeBaseline baseline = existing.orElseGet(UncertaintyScopeBaseline::new);
        baseline.setCalculationTemplateId(calculationTemplateId);
        baseline.setScope(scope);
        baseline.setBenchmarkQty(benchmarkQty);
        baseline.setBenchmarkUnit(unit);
        baseline.setBenchmarkSource(source);
        baseline.setUpdatedAt(LocalDateTime.now());
        uncertaintyScopeBaselineRepository.save(baseline);
    }

    @Override
    public List<UncertaintyScopeBaseline> listBaselines(Long calculationTemplateId) {
        return uncertaintyScopeBaselineRepository.findByCalculationTemplateId(calculationTemplateId);
    }

    /**
     * 计算单个 Scope 的完整性分量（5.13.1-5.13.4）
     */
    private ScopeCompletenessResult computeOneScope(Long calculationTemplateId, String scope,
                                                    List<UncertaintySourceMeta> group,
                                                    BigDecimal deltaCap, BigDecimal coverageAlpha) {
        ScopeCompletenessResult result = new ScopeCompletenessResult();
        result.setScope(scope);
        if (UNGROUPED.equals(scope)) {
            result.getWarnings().add("W15: 存在未填写Scope类别的排放源，已归入\"" + UNGROUPED + "\"分组处理");
        }

        // 排放量小计 E[g]、直采排放量、点数统计（emission_value 为空的记录按 0 计）
        BigDecimal scopeEmission = BigDecimal.ZERO;
        BigDecimal measuredEmission = BigDecimal.ZERO;
        int directCount = 0;
        boolean tierDistinguishable = true;
        for (UncertaintySourceMeta source : group) {
            BigDecimal emission = source.getEmissionValue() != null
                    ? source.getEmissionValue() : BigDecimal.ZERO;
            scopeEmission = scopeEmission.add(emission);
            String tier = source.getAdMeteringTier();
            if (tier == null || tier.isBlank()) {
                tierDistinguishable = false;
            }
            if (tier != null && DIRECT_TIERS.contains(tier)) {
                measuredEmission = measuredEmission.add(emission);
                directCount++;
            }
        }
        result.setScopeEmission(scopeEmission.setScale(SCALE, RoundingMode.HALF_UP));

        // 点数比 x/n（仅诊断指标，不参与计算）
        BigDecimal pointRatioXn = null;
        if (!group.isEmpty()) {
            pointRatioXn = BigDecimal.valueOf(directCount)
                    .divide(BigDecimal.valueOf(group.size()), SCALE, RoundingMode.HALF_UP);
            result.setPointRatioXn(pointRatioXn);
        }

        // r_measured：E[g]≤0 视为不可计算
        BigDecimal rMeasured = null;
        if (scopeEmission.compareTo(BigDecimal.ZERO) > 0) {
            rMeasured = measuredEmission.divide(scopeEmission, SCALE, RoundingMode.HALF_UP);
            result.setRMeasured(rMeasured);
        }

        // W17：点数比与排放量加权支撑度严重背离（仅诊断，不影响计算）
        if (pointRatioXn != null && rMeasured != null
                && pointRatioXn.subtract(rMeasured).abs().compareTo(new BigDecimal("0.3")) > 0) {
            result.getWarnings().add("W17: Scope " + scope + " 点数比x/n(" + pointRatioXn
                    + ")与排放量加权计量支撑度r_measured(" + rMeasured + ")偏差超过0.3，请核查大排放源计量方式");
        }

        // 判据分支：查 I6 独立基准
        Optional<UncertaintyScopeBaseline> baselineOpt = uncertaintyScopeBaselineRepository
                .findByCalculationTemplateIdAndScope(calculationTemplateId, scope);
        BigDecimal rEff;
        if (baselineOpt.isPresent() && baselineOpt.get().getBenchmarkQty() != null
                && baselineOpt.get().getBenchmarkQty().compareTo(BigDecimal.ZERO) > 0) {
            // 有 benchmark：r_benchmark=Σad_value/benchmark_qty，r_eff=min(r_benchmark, r_measured)
            UncertaintyScopeBaseline baseline = baselineOpt.get();
            result.setBasis(BASIS_BENCHMARK_MEASURED);
            result.setBenchmarkQty(baseline.getBenchmarkQty());
            result.setBenchmarkSource(baseline.getBenchmarkSource());

            BigDecimal adSum = BigDecimal.ZERO;
            for (UncertaintySourceMeta source : group) {
                if (source.getAdValue() != null) {
                    adSum = adSum.add(source.getAdValue());
                }
            }
            BigDecimal rBenchmark = adSum.divide(baseline.getBenchmarkQty(), SCALE, RoundingMode.HALF_UP);
            result.setRBenchmark(rBenchmark);
            // r_measured 不可计算（E[g]≤0）时退化为 r_benchmark
            rEff = rMeasured != null ? rBenchmark.min(rMeasured) : rBenchmark;

            // W16：已报活动数据超过独立基准，数据异常（照常按分段处理但标注异常）
            if (rBenchmark.compareTo(new BigDecimal("1.01")) > 0) {
                result.getWarnings().add("W16: Scope " + scope + " 的r_benchmark=" + rBenchmark
                        + "大于1.01，已报活动数据超过独立基准，存在口径不一致或基准过期风险");
            }
        } else if (scopeEmission.compareTo(BigDecimal.ZERO) > 0 && tierDistinguishable) {
            // 无 benchmark 但可区分直采/估算：r_eff=r_measured
            result.setBasis(BASIS_MEASURED);
            rEff = rMeasured;
            result.setDisclosure("Scope " + scope
                    + " 的完整性仅依据已报数据计量方式评估，仅反映已报数据中估算占比，不含遗漏风险");
            result.getWarnings().add("W15: Scope " + scope
                    + " 未提供独立自上而下基准，r_eff 仅反映已报数据中估算占比，不含遗漏风险");
        } else {
            // 既无基准也无法区分：disabled，ξ_cov≡1，强制披露（5.13.4 模板）
            result.setBasis(BASIS_DISABLED);
            result.setDeltaCovPercent(BigDecimal.ZERO.setScale(SCALE, RoundingMode.HALF_UP));
            result.setEXiCov(BigDecimal.ONE.setScale(SCALE, RoundingMode.HALF_UP));
            result.setDisclosure(buildDisabledDisclosure(scope));
            result.getWarnings().add("W15: Scope " + scope
                    + " 完整性未经独立基准验证且无法区分直采/估算，未施加遗漏修正分量，须强制披露");
            return result;
        }

        // δ_cov 分段（5.13.2，左闭右开：>0.95→5；0.80≤r≤0.95→12；0.60≤r<0.80→20；其余封顶）
        BigDecimal deltaCov = segmentDeltaCov(rEff, deltaCap);
        result.setDeltaCovPercent(deltaCov.setScale(SCALE, RoundingMode.HALF_UP));

        // E[ξ_cov]=1+(δ_cov/100)/(α_cov+1)，其中 E[Beta(1,α_cov)]=1/(1+α_cov)
        BigDecimal eXiCov = BigDecimal.ONE.add(deltaCov.divide(BigDecimal.valueOf(100), SCALE, RoundingMode.HALF_UP)
                .divide(coverageAlpha.add(BigDecimal.ONE), SCALE, RoundingMode.HALF_UP));
        result.setEXiCov(eXiCov.setScale(SCALE, RoundingMode.HALF_UP));
        return result;
    }

    /**
     * δ_cov 分段表（5.13.2）
     *
     * @param rEff     r_eff=min(r_benchmark, r_measured) 或 r_measured
     * @param deltaCap 封顶值（规则库 coverage_delta_cap，默认30）
     * @return delta_cov_percent
     */
    private BigDecimal segmentDeltaCov(BigDecimal rEff, BigDecimal deltaCap) {
        if (rEff.compareTo(new BigDecimal("0.95")) > 0) {
            return new BigDecimal("5");
        }
        if (rEff.compareTo(new BigDecimal("0.80")) >= 0) {
            return new BigDecimal("12");
        }
        if (rEff.compareTo(new BigDecimal("0.60")) >= 0) {
            return new BigDecimal("20");
        }
        return deltaCap;
    }

    /**
     * basis=disabled 时的强制披露文案（5.13.4 模板）
     */
    private String buildDisabledDisclosure(String scope) {
        return "Scope " + scope + " 的完整性未经独立自上而下基准验证，本核算未对该 Scope 施加遗漏修正分量。"
                + "E_point 应理解为在'清单已涵盖全部应核算源'假设下的结果；若存在未纳入的排放源，"
                + "实际排放量将高于本报告值。建议后续补充{供电局结算单/设施台账/运量反算}等独立基准以启用完整性量化。";
    }

    /**
     * Scope 分组键：空 scope 归入"未分组"
     */
    private static String scopeKey(String scope) {
        return (scope == null || scope.isBlank()) ? UNGROUPED : scope;
    }
}
