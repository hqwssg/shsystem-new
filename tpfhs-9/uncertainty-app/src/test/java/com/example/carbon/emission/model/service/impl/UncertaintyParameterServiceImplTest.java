package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.ParamResultData;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.offset;

/**
 * UncertaintyParameterServiceImpl 单元测试（纯 Mockito，不启动 Spring 容器）
 * <p>
 * 覆盖 M3 参数化：公式(38) 加权归一化、表4-4 等价式 SDQI、δ 查表、
 * α=β=SDQI²、支撑区间因子、自定义权重与权重=0 禁用、final_score 缺失标记。
 * 对应规范用例 T1/T2/T3/T21/T55/T56。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("不确定性参数化服务测试（M3）")
class UncertaintyParameterServiceImplTest {

    private static final String[] AD_DIMS = {"A1", "A2", "A4", "A5", "A6"};
    private static final String[] EF_DIMS = {"E1", "E2", "E3", "E4", "E5", "E6"};

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private UncertaintyParameterServiceImpl service;

    // ========================= 测试前置数据构造 =========================

    /** 规则库：δ 表按规范 5.3 默认值 */
    private UncertaintyRuleset ruleset() {
        UncertaintyRuleset r = new UncertaintyRuleset();
        r.setId(1L);
        r.setRulesetVersion("DQI-RULES-2026.12");
        r.setDeltaTable("{\"5.0\":5,\"4.5\":8,\"4.0\":12,\"3.5\":16,\"3.0\":20,"
                + "\"2.5\":30,\"2.0\":40,\"1.5\":60,\"1.0\":100}");
        return r;
    }

    private UncertaintyDimensionRule dimRule(String appliesTo, String dimCode, double weight) {
        UncertaintyDimensionRule r = new UncertaintyDimensionRule();
        r.setRulesetId(1L);
        r.setAppliesTo(appliesTo);
        r.setDimCode(dimCode);
        r.setDimName(dimCode);
        r.setEnabled(1);
        r.setWeight(BigDecimal.valueOf(weight));
        r.setDriver("driver");
        r.setRuleType("mapping");
        return r;
    }

    /** AD 五维规则，weights 与 A1/A2/A4/A5/A6 一一对应 */
    private List<UncertaintyDimensionRule> adRules(double... weights) {
        List<UncertaintyDimensionRule> rules = new ArrayList<>();
        for (int i = 0; i < AD_DIMS.length; i++) {
            rules.add(dimRule("AD", AD_DIMS[i], weights[i]));
        }
        return rules;
    }

    /** EF 六维等权规则 */
    private List<UncertaintyDimensionRule> efRules() {
        List<UncertaintyDimensionRule> rules = new ArrayList<>();
        for (String dim : EF_DIMS) {
            rules.add(dimRule("EF", dim, 1.0));
        }
        return rules;
    }

    /** 构造评分行，dimScores 与维度顺序一一对应 */
    private List<UncertaintyScore> scores(String paramType, String[] dims, int... finalScores) {
        List<UncertaintyScore> list = new ArrayList<>();
        for (int i = 0; i < dims.length; i++) {
            UncertaintyScore s = new UncertaintyScore();
            s.setSourceMetaId(1L);
            s.setParamType(paramType);
            s.setDimCode(dims[i]);
            s.setFinalScore(finalScores[i]);
            list.add(s);
        }
        return list;
    }

    private ParamResultData parameterizeAd(List<UncertaintyDimensionRule> rules, List<UncertaintyScore> scores) {
        return service.parameterize(new UncertaintySourceMeta(), scores, ruleset(), rules, "AD");
    }

    private void assertClose(double expected, BigDecimal actual) {
        assertThat(actual).isNotNull();
        assertThat(actual.doubleValue()).isCloseTo(expected, offset(1e-6));
    }

    // ========================= 用例 =========================

    @Test
    @DisplayName("T1: AD 五维全5（等权）→ ∑Q=25、x=100、SDQI=5.0、α=β=25、δ=5、support=[0.95,1.05]")
    void t1_adAllFive_equalWeights() {
        ParamResultData r = parameterizeAd(adRules(1, 1, 1, 1, 1), scores("AD", AD_DIMS, 5, 5, 5, 5, 5));
        assertThat(r.isIncomplete()).isFalse();
        assertClose(25.0, r.getSumQW());
        assertClose(5.0, r.getSumQMinW());
        assertClose(25.0, r.getSumQMaxW());
        assertClose(100.0, r.getXPercent());
        assertClose(5.0, r.getSdqi());
        assertClose(25.0, r.getBetaAlpha());
        assertClose(25.0, r.getBetaBeta());
        assertClose(5.0, r.getDeltaPercent());
        assertClose(0.95, r.getSupportLowFactor());
        assertClose(1.05, r.getSupportHighFactor());
    }

    @Test
    @DisplayName("T2: EF 六维全5 → x=100、SDQI=5.0")
    void t2_efAllFive() {
        ParamResultData r = service.parameterize(new UncertaintySourceMeta(),
                scores("EF", EF_DIMS, 5, 5, 5, 5, 5, 5), ruleset(), efRules(), "EF");
        assertThat(r.isIncomplete()).isFalse();
        assertClose(30.0, r.getSumQW());
        assertClose(6.0, r.getSumQMinW());
        assertClose(30.0, r.getSumQMaxW());
        assertClose(100.0, r.getXPercent());
        assertClose(5.0, r.getSdqi());
    }

    @Test
    @DisplayName("T3-AD: ∑Q=23 → x=90 → SDQI=4.5、δ=8")
    void t3_adBoundary_sum23() {
        ParamResultData r = parameterizeAd(adRules(1, 1, 1, 1, 1), scores("AD", AD_DIMS, 5, 5, 5, 4, 4));
        assertClose(23.0, r.getSumQW());
        assertClose(90.0, r.getXPercent());
        assertClose(4.5, r.getSdqi());
        assertClose(8.0, r.getDeltaPercent());
        assertClose(20.25, r.getBetaAlpha());
        assertClose(0.92, r.getSupportLowFactor());
        assertClose(1.08, r.getSupportHighFactor());
    }

    @Test
    @DisplayName("T3-EF: ∑Q=20 → x≈58.33 → SDQI=3.0、δ=20、α=β=9")
    void t3_efBoundary_sum20() {
        ParamResultData r = service.parameterize(new UncertaintySourceMeta(),
                scores("EF", EF_DIMS, 4, 4, 3, 3, 3, 3), ruleset(), efRules(), "EF");
        assertClose(20.0, r.getSumQW());
        assertClose(58.3333, r.getXPercent());
        assertClose(3.0, r.getSdqi());
        assertClose(20.0, r.getDeltaPercent());
        assertClose(9.0, r.getBetaAlpha());
        assertClose(9.0, r.getBetaBeta());
        assertClose(0.80, r.getSupportLowFactor());
        assertClose(1.20, r.getSupportHighFactor());
    }

    @Test
    @DisplayName("T21/T55: 自定义权重 A1=2 其余1 → ∑Q=26、∑Qmin=6、∑Qmax=30、x≈83.33 → SDQI=4.0")
    void t21_customWeight_a1Doubled() {
        ParamResultData r = parameterizeAd(adRules(2, 1, 1, 1, 1), scores("AD", AD_DIMS, 5, 4, 4, 4, 4));
        assertClose(26.0, r.getSumQW());
        assertClose(6.0, r.getSumQMinW());
        assertClose(30.0, r.getSumQMaxW());
        assertClose(83.3333, r.getXPercent());
        assertClose(4.0, r.getSdqi());
        assertClose(12.0, r.getDeltaPercent());
        assertClose(16.0, r.getBetaAlpha());
    }

    @Test
    @DisplayName("T56: 权重=0 禁用 A2 → A2 不参与归一化，∑Qmin=4、∑Qmax=20")
    void t56_zeroWeight_disablesDim() {
        ParamResultData r = parameterizeAd(adRules(1, 0, 1, 1, 1), scores("AD", AD_DIMS, 5, 5, 5, 5, 5));
        assertThat(r.isIncomplete()).isFalse();
        assertClose(20.0, r.getSumQW());
        assertClose(4.0, r.getSumQMinW());
        assertClose(20.0, r.getSumQMaxW());
        assertClose(100.0, r.getXPercent());
        assertClose(5.0, r.getSdqi());
    }

    @Test
    @DisplayName("final_score 缺失 → incomplete=true 且不再计算 x/SDQI/δ")
    void missingFinalScore_incomplete() {
        List<UncertaintyScore> scores = scores("AD", AD_DIMS, 5, 5, 5, 5, 5);
        scores.get(4).setFinalScore(null);
        ParamResultData r = parameterizeAd(adRules(1, 1, 1, 1, 1), scores);
        assertThat(r.isIncomplete()).isTrue();
        assertThat(r.getWarnings()).anyMatch(w -> w.contains("A6") && w.contains("不完整"));
        assertThat(r.getXPercent()).isNull();
        assertThat(r.getSdqi()).isNull();
        assertThat(r.getDeltaPercent()).isNull();
    }
}
