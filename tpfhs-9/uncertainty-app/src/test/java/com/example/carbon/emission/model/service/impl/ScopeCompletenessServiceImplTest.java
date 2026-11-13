package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.ScopeCompletenessResult;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScopeBaseline;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.repository.UncertaintyScopeBaselineRepository;
import com.example.carbon.emission.model.repository.UncertaintySourceMetaRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.offset;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * ScopeCompletenessServiceImpl 单元测试（纯 Mockito，不启动 Spring 容器）
 * <p>
 * 覆盖规范 5.13：r_measured/r_benchmark 定义与联合取 min、delta_cov_percent 直接分段
 * （封顶 coverage_delta_cap=30）、E[ξ_cov]=1+(δ/100)/16（α_cov=15）、
 * basis 三档判定（benchmark_measured/measured/disabled）、强制披露、W15/W16/W17。
 * 对应规范用例 T42/T43/T46/T57/T58。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("Scope 级完整性分量服务测试（5.13）")
class ScopeCompletenessServiceImplTest {

    private static final Long TEMPLATE_ID = 100L;
    private static final String SCOPE = "scope2";

    @Mock
    private UncertaintySourceMetaRepository uncertaintySourceMetaRepository;

    @Mock
    private UncertaintyScopeBaselineRepository uncertaintyScopeBaselineRepository;

    @InjectMocks
    private ScopeCompletenessServiceImpl service;

    // ========================= 测试前置数据构造 =========================

    /** 规则库：封顶 30%、α_cov=15（规范默认值） */
    private UncertaintyRuleset ruleset() {
        UncertaintyRuleset r = new UncertaintyRuleset();
        r.setId(1L);
        r.setRulesetVersion("DQI-RULES-2026.12");
        r.setCoverageDeltaCap(new BigDecimal("30"));
        r.setCoverageAlpha(new BigDecimal("15"));
        return r;
    }

    private UncertaintySourceMeta source(String scope, String tier, String emission, String adValue) {
        UncertaintySourceMeta s = new UncertaintySourceMeta();
        s.setCalculationTemplateId(TEMPLATE_ID);
        s.setSourceName("源");
        s.setScope(scope);
        s.setAdMeteringTier(tier);
        s.setEmissionValue(emission != null ? new BigDecimal(emission) : null);
        s.setAdValue(adValue != null ? new BigDecimal(adValue) : null);
        return s;
    }

    /** 无基准场景：直采 E=directE + 估算 E=estE（tier 均可区分），返回唯一 Scope 结果 */
    private ScopeCompletenessResult computeMeasured(String directE, String estE) {
        when(uncertaintySourceMetaRepository.findByCalculationTemplateId(TEMPLATE_ID))
                .thenReturn(List.of(
                        source(SCOPE, "online_meter", directE, null),
                        source(SCOPE, "default_or_estimated", estE, null)));
        when(uncertaintyScopeBaselineRepository.findByCalculationTemplateIdAndScope(eq(TEMPLATE_ID), anyString()))
                .thenReturn(Optional.empty());
        return service.compute(TEMPLATE_ID, ruleset()).get(0);
    }

    private void assertClose(double expected, BigDecimal actual) {
        assertThat(actual).isNotNull();
        assertThat(actual.doubleValue()).isCloseTo(expected, offset(1e-6));
    }

    // ========================= 用例 =========================

    @Test
    @DisplayName("T57: δ_cov 直接分段 → 0.96→5、0.87→12、0.70→20、0.50→30(封顶)、0.30→30(封顶)")
    void t57_deltaCovSegmentation() {
        // r_eff=0.96 → 5%，E[ξ_cov]=1+0.05/16=1.003125
        ScopeCompletenessResult r1 = computeMeasured("96", "4");
        assertClose(5.0, r1.getDeltaCovPercent());
        assertClose(1.003125, r1.getEXiCov());

        // r_eff=0.87 → 12%，E[ξ_cov]=1+0.12/16=1.0075
        ScopeCompletenessResult r2 = computeMeasured("87", "13");
        assertClose(12.0, r2.getDeltaCovPercent());
        assertClose(1.0075, r2.getEXiCov());

        // r_eff=0.70 → 20%，E[ξ_cov]=1+0.20/16=1.0125
        ScopeCompletenessResult r3 = computeMeasured("70", "30");
        assertClose(20.0, r3.getDeltaCovPercent());
        assertClose(1.0125, r3.getEXiCov());

        // r_eff=0.50 → 30%（封顶），E[ξ_cov]=1+0.30/16=1.01875
        ScopeCompletenessResult r4 = computeMeasured("50", "50");
        assertClose(30.0, r4.getDeltaCovPercent());
        assertClose(1.01875, r4.getEXiCov());

        // r_eff=0.30 → 30%（封顶）
        ScopeCompletenessResult r5 = computeMeasured("30", "70");
        assertClose(30.0, r5.getDeltaCovPercent());
        assertClose(1.01875, r5.getEXiCov());
    }

    @Test
    @DisplayName("T42/T43: 联合取 min → benchmark=766、直采 E=726+估算 20×2 → basis=benchmark_measured、δ=12、W17")
    void t42_benchmarkMeasured_jointMin() {
        List<UncertaintySourceMeta> sources = new ArrayList<>();
        sources.add(source(SCOPE, "online_meter", "726", "766"));
        for (int i = 0; i < 20; i++) {
            sources.add(source(SCOPE, "default_or_estimated", "2", null));
        }
        UncertaintyScopeBaseline baseline = new UncertaintyScopeBaseline();
        baseline.setCalculationTemplateId(TEMPLATE_ID);
        baseline.setScope(SCOPE);
        baseline.setBenchmarkQty(new BigDecimal("766"));
        baseline.setBenchmarkSource("供电局结算单");

        when(uncertaintySourceMetaRepository.findByCalculationTemplateId(TEMPLATE_ID)).thenReturn(sources);
        when(uncertaintyScopeBaselineRepository.findByCalculationTemplateIdAndScope(TEMPLATE_ID, SCOPE))
                .thenReturn(Optional.of(baseline));

        ScopeCompletenessResult r = service.compute(TEMPLATE_ID, ruleset()).get(0);

        assertThat(r.getBasis()).isEqualTo("benchmark_measured");
        assertClose(766.0, r.getScopeEmission());
        assertClose(1.0, r.getRBenchmark());
        // r_measured=726/766≈0.947780（规范记作 0.948）
        assertClose(726.0 / 766.0, r.getRMeasured());
        assertThat(r.getRMeasured().doubleValue()).isCloseTo(0.948, offset(1e-3));
        // r_eff=min(1.0, 0.948)=0.948 → δ=12%，E[ξ_cov]=1.0075
        assertClose(12.0, r.getDeltaCovPercent());
        assertClose(1.0075, r.getEXiCov());
        // 点数比 x/n=1/21≈0.0476，与 r_measured 偏差>0.3 → W17
        assertClose(1.0 / 21.0, r.getPointRatioXn());
        assertThat(r.getWarnings()).anyMatch(w -> w.contains("W17"));
        assertThat(r.getWarnings()).noneMatch(w -> w.contains("W16"));
    }

    @Test
    @DisplayName("T58: 无 benchmark 可区分直采 → basis=measured、按 r_measured 查档、W15")
    void t58_noBenchmark_distinguishable_basisMeasured() {
        ScopeCompletenessResult r = computeMeasured("87", "13");
        assertThat(r.getBasis()).isEqualTo("measured");
        assertClose(0.87, r.getRMeasured());
        assertThat(r.getRBenchmark()).isNull();
        assertClose(12.0, r.getDeltaCovPercent());
        assertClose(1.0075, r.getEXiCov());
        assertThat(r.getDisclosure()).contains("不含遗漏风险");
        assertThat(r.getWarnings()).anyMatch(w -> w.contains("W15"));
    }

    @Test
    @DisplayName("T46/T58: 无 benchmark 且 tier 全空不可区分 → basis=disabled、δ=0、E[ξ_cov]=1、强制披露、W15")
    void t46_noBenchmark_indistinguishable_basisDisabled() {
        when(uncertaintySourceMetaRepository.findByCalculationTemplateId(TEMPLATE_ID))
                .thenReturn(List.of(
                        source(SCOPE, null, "50", null),
                        source(SCOPE, null, "30", null)));
        when(uncertaintyScopeBaselineRepository.findByCalculationTemplateIdAndScope(eq(TEMPLATE_ID), anyString()))
                .thenReturn(Optional.empty());

        ScopeCompletenessResult r = service.compute(TEMPLATE_ID, ruleset()).get(0);

        assertThat(r.getBasis()).isEqualTo("disabled");
        assertClose(0.0, r.getDeltaCovPercent());
        assertClose(1.0, r.getEXiCov());
        assertThat(r.getDisclosure()).isNotBlank();
        assertThat(r.getDisclosure()).contains("未经独立自上而下基准验证");
        assertThat(r.getWarnings()).anyMatch(w -> w.contains("W15"));
    }

    @Test
    @DisplayName("W16: r_benchmark>1.01 → 触发 W16，δ 仍按 r_eff 分段")
    void w16_benchmarkExceeded() {
        List<UncertaintySourceMeta> sources = List.of(
                source(SCOPE, "online_meter", "120", "120"));
        UncertaintyScopeBaseline baseline = new UncertaintyScopeBaseline();
        baseline.setCalculationTemplateId(TEMPLATE_ID);
        baseline.setScope(SCOPE);
        baseline.setBenchmarkQty(new BigDecimal("100"));

        when(uncertaintySourceMetaRepository.findByCalculationTemplateId(TEMPLATE_ID)).thenReturn(sources);
        when(uncertaintyScopeBaselineRepository.findByCalculationTemplateIdAndScope(TEMPLATE_ID, SCOPE))
                .thenReturn(Optional.of(baseline));

        ScopeCompletenessResult r = service.compute(TEMPLATE_ID, ruleset()).get(0);

        assertThat(r.getBasis()).isEqualTo("benchmark_measured");
        assertClose(1.2, r.getRBenchmark());
        assertThat(r.getWarnings()).anyMatch(w -> w.contains("W16"));
        // r_eff=min(1.2, 1.0)=1.0 → δ=5%
        assertClose(1.0, r.getRMeasured());
        assertClose(5.0, r.getDeltaCovPercent());
    }
}
