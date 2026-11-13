package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.DqiDimSuggestionDto;
import com.example.carbon.emission.model.dto.DqiScoreSubmitItem;
import com.example.carbon.emission.model.dto.DqiScoreSubmitRequest;
import com.example.carbon.emission.model.dto.DqiSuggestionDto;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.repository.CalculationNodeDataRepository;
import com.example.carbon.emission.model.repository.CalculationNodeRepository;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.UncertaintyAuditRepository;
import com.example.carbon.emission.model.repository.UncertaintyDimensionRuleRepository;
import com.example.carbon.emission.model.repository.UncertaintyRulesetRepository;
import com.example.carbon.emission.model.repository.UncertaintyScoreRepository;
import com.example.carbon.emission.model.repository.UncertaintySourceMetaRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * DqiScoringServiceImpl 单元测试（纯 Mockito，不启动 Spring 容器）
 * <p>
 * 覆盖 M2a 自动评分五步框架：mapping/band/direct_score 求值、AD/EF 时间阈值分离、
 * A6 record/excluded 类处理、A2 中性分、ad_geo_basis 默认填充、缺失转人工、
 * 软校验 W1/W2/W3，以及 submitScores 对 excluded 类 A6 的强制回写。
 * 规则库数据按规范 5.9 默认值在测试夹具内构造（dimension_weights 全 1 等权）。
 * 对应规范用例 T9/T11/T12/T13/T26/T31/T36/T37/T40/T41/T53/T54。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("DQI 自动评分服务测试（M2a）")
class DqiScoringServiceImplTest {

    private static final Long TEMPLATE_ID = 100L;
    private static final Long SOURCE_ID = 1000L;
    private static final String RULESET_VERSION = "DQI-RULES-2026.12";
    private static final int CALC_YEAR = 2026;

    @Mock
    private UncertaintySourceMetaRepository sourceMetaRepository;

    @Mock
    private UncertaintyScoreRepository scoreRepository;

    @Mock
    private UncertaintyAuditRepository auditRepository;

    @Mock
    private UncertaintyRulesetRepository rulesetRepository;

    @Mock
    private UncertaintyDimensionRuleRepository dimensionRuleRepository;

    @Mock
    private CalculationTemplateRepository calculationTemplateRepository;

    @Mock
    private CalculationNodeRepository calculationNodeRepository;

    @Mock
    private CalculationNodeDataRepository calculationNodeDataRepository;

    @Mock
    private EmissionNodeRepository emissionNodeRepository;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private DqiScoringServiceImpl service;

    // ========================= 测试前置数据构造（规范 5.9 规则库默认值） =========================

    /** 规则库版本：dimension_weights 全 1 等权 */
    private UncertaintyRuleset ruleset() {
        UncertaintyRuleset r = new UncertaintyRuleset();
        r.setId(1L);
        r.setRulesetVersion(RULESET_VERSION);
        r.setDimensionWeights("{\"AD\":{\"A1\":1.0,\"A2\":1.0,\"A4\":1.0,\"A5\":1.0,\"A6\":1.0},"
                + "\"EF\":{\"E1\":1.0,\"E2\":1.0,\"E3\":1.0,\"E4\":1.0,\"E5\":1.0,\"E6\":1.0}}");
        return r;
    }

    private UncertaintyDimensionRule baseRule(String appliesTo, String dimCode, String driver) {
        UncertaintyDimensionRule r = new UncertaintyDimensionRule();
        r.setRulesetId(1L);
        r.setAppliesTo(appliesTo);
        r.setDimCode(dimCode);
        r.setDimName(dimCode);
        r.setEnabled(1);
        r.setWeight(BigDecimal.ONE);
        r.setDriver(driver);
        r.setNullPolicy("to_manual");
        return r;
    }

    private UncertaintyDimensionRule mappingRule(String appliesTo, String dimCode, String driver, String entries) {
        UncertaintyDimensionRule r = baseRule(appliesTo, dimCode, driver);
        r.setRuleType("mapping");
        r.setEntries(entries);
        return r;
    }

    /** 11 个维度规则（AD 五维 + EF 六维），entries 按规范 5.9 默认映射 */
    private List<UncertaintyDimensionRule> allDimRules() {
        List<UncertaintyDimensionRule> rules = new ArrayList<>();
        rules.add(mappingRule("AD", "A1", "ad_metering_tier",
                "{\"online_meter\":5,\"manual_ledger\":4,\"statistical_report\":3,"
                        + "\"literature_thirdparty\":2,\"default_or_estimated\":1}"));

        UncertaintyDimensionRule a2 = mappingRule("AD", "A2", "ad_meter_calibration",
                "{\"calib_valid_cert\":5,\"calib_valid_internal\":4,\"calib_overdue_verified\":3,"
                        + "\"calib_overdue_no_record\":2,\"calib_status_unknown\":1}");
        a2.setNullPolicy("neutral");
        a2.setNeutralScore(3);
        a2.setNeutralWhenValue("calib_not_applicable");
        rules.add(a2);

        UncertaintyDimensionRule a4 = mappingRule("AD", "A4", "ad_geo_basis",
                "{\"direct_metered\":5,\"ledger_complete\":4,\"allocated\":3,"
                        + "\"analogized\":2,\"default_value\":1}");
        a4.setNullPolicy("default_with_flag");
        a4.setDefaultValue("direct_metered");
        a4.setMarkDefaultFilled(1);
        rules.add(a4);

        UncertaintyDimensionRule a5 = baseRule("AD", "A5", "delta_year");
        a5.setRuleType("band");
        a5.setValidRange("[0,999]");
        a5.setOutOfRangeWarning("Δt<0：数据年份晚于核算年度，逻辑异常，须核实 ad_data_year 或 calc_year");
        a5.setEntries("[[-99,1,5],[1,2,4],[2,3,3],[3,4,2],[4,999,1]]");
        rules.add(a5);

        UncertaintyDimensionRule a6 = baseRule("AD", "A6", "ad_data_collection_quality");
        a6.setRuleType("direct_score");
        a6.setEntries("{}");
        rules.add(a6);

        rules.add(mappingRule("EF", "E1", "ef_source_authority",
                "{\"official_national\":5,\"national_standard\":4,\"ipcc_default\":3,"
                        + "\"authoritative_literature\":2,\"general_or_estimated\":1}"));
        rules.add(mappingRule("EF", "E2", "ef_completeness_scope",
                "{\"full\":5,\"minor_missing\":4,\"partial_missing\":3,\"major_only\":2,\"unknown\":1}"));
        rules.add(mappingRule("EF", "E3", "ef_data_region",
                "{\"in_boundary\":5,\"same_grid\":4,\"national\":3,\"similar_economy\":2,\"other_country\":1}"));

        UncertaintyDimensionRule e4 = baseRule("EF", "E4", "delta_year");
        e4.setRuleType("band");
        e4.setValidRange("[0,999]");
        e4.setOutOfRangeWarning("Δt<0：因子年份晚于核算年度，逻辑异常，须核实 ef_data_year 或 calc_year");
        e4.setEntries("[[-99,3,5],[3,4,4],[4,5,3],[5,6,2],[6,999,1]]");
        rules.add(e4);

        rules.add(mappingRule("EF", "E5", "ef_tech_applicability",
                "{\"same_equipment_condition\":5,\"railway_same_traction\":4,\"railway_generic\":3,"
                        + "\"adjacent_industry\":2,\"generic_default\":1}"));
        rules.add(mappingRule("EF", "E6", "ef_conversion_chain",
                "{\"direct_match\":5,\"standard_single\":4,\"multi_step\":3,"
                        + "\"derived_from_other\":2,\"unclear\":1}"));
        return rules;
    }

    /** 全优基准排放源（T9 输入）：AD/EF 全部驱动字段取 5 分枚举值，年份=核算年度 */
    private UncertaintySourceMeta baseSource() {
        UncertaintySourceMeta s = new UncertaintySourceMeta();
        s.setId(SOURCE_ID);
        s.setCalculationTemplateId(TEMPLATE_ID);
        s.setSourceName("测试排放源");
        s.setScope("scope1");
        s.setAdValue(new BigDecimal("766"));
        s.setEmissionValue(new BigDecimal("726"));
        s.setAdMeteringTier("online_meter");
        s.setAdMeterCalibration("calib_valid_cert");
        s.setAdGeoBasis("direct_metered");
        s.setAdDataYear(CALC_YEAR);
        s.setAdDataCollectionQuality(5);
        s.setEfSourceAuthority("official_national");
        s.setEfCompletenessScope("full");
        s.setEfDataRegion("in_boundary");
        s.setEfDataYear(CALC_YEAR);
        s.setEfTechApplicability("same_equipment_condition");
        s.setEfConversionChain("direct_match");
        return s;
    }

    /** 装配 generateSuggestions 所需全部 mock 并执行 */
    private List<DqiSuggestionDto> generate(UncertaintySourceMeta... sources) {
        UncertaintyRuleset ruleset = ruleset();
        when(rulesetRepository.findByRulesetVersion(RULESET_VERSION)).thenReturn(Optional.of(ruleset));
        when(dimensionRuleRepository.findByRulesetId(ruleset.getId())).thenReturn(allDimRules());
        CalculationTemplate template = new CalculationTemplate();
        template.setId(TEMPLATE_ID);
        when(calculationTemplateRepository.findById(TEMPLATE_ID)).thenReturn(Optional.of(template));
        when(sourceMetaRepository.findByCalculationTemplateId(TEMPLATE_ID)).thenReturn(List.of(sources));
        for (UncertaintySourceMeta s : sources) {
            when(scoreRepository.findBySourceMetaId(s.getId())).thenReturn(List.of());
        }
        when(scoreRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));
        return service.generateSuggestions(TEMPLATE_ID, RULESET_VERSION, CALC_YEAR);
    }

    private DqiDimSuggestionDto dim(DqiSuggestionDto dto, String dimCode) {
        return dto.getDimensions().stream()
                .filter(d -> dimCode.equals(d.getDimCode()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("缺少维度 " + dimCode));
    }

    // ========================= 用例 =========================

    @Test
    @DisplayName("T9: 全优 AD 映射 → A1/A2/A4/A5/A6 全 5，状态 complete")
    void t9_allExcellentAd_allDimsScore5() {
        List<DqiSuggestionDto> result = generate(baseSource());
        assertThat(result).hasSize(1);
        DqiSuggestionDto dto = result.get(0);
        for (String dimCode : List.of("A1", "A2", "A4", "A5", "A6")) {
            DqiDimSuggestionDto d = dim(dto, dimCode);
            assertThat(d.getSuggested()).as(dimCode + " 建议分").isEqualTo(5);
            assertThat(d.getStatus()).as(dimCode + " 状态").isEqualTo("complete");
            assertThat(d.getEvidence()).as(dimCode + " 判定依据").isNotBlank();
        }
        assertThat(dim(dto, "A6").getA6Source()).isEqualTo("normal");
        assertThat(dim(dto, "A4").getDefaultFilled()).isFalse();
        // EF 六维同样全 5（官方因子全优输入）
        for (String dimCode : List.of("E1", "E2", "E3", "E4", "E5", "E6")) {
            assertThat(dim(dto, dimCode).getSuggested()).as(dimCode + " 建议分").isEqualTo(5);
        }
        assertThat(dto.getWarnings()).isEmpty();
        assertThat(dto.getCalcYear()).isEqualTo(CALC_YEAR);
        assertThat(dto.getRulesetVersion()).isEqualTo(RULESET_VERSION);
    }

    @Test
    @DisplayName("T11: AD/EF 时间阈值分离 → Δt=3 时 A5=2、E4=4")
    void t11_timeThresholdSeparation_adStricterThanEf() {
        UncertaintySourceMeta s = baseSource();
        s.setAdDataYear(CALC_YEAR - 3);
        s.setEfDataYear(CALC_YEAR - 3);
        DqiSuggestionDto dto = generate(s).get(0);
        assertThat(dim(dto, "A5").getSuggested()).isEqualTo(2);
        assertThat(dim(dto, "A5").getEvidence()).contains("Δt=3");
        assertThat(dim(dto, "E4").getSuggested()).isEqualTo(4);
        assertThat(dim(dto, "E4").getEvidence()).contains("Δt=3");
    }

    @Test
    @DisplayName("T31: A4 与 A5 职责边界 → analogized+Δt=0 时 A4=2、A5=5")
    void t31_a4A5Boundary_analogizedCurrentYear() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("manual_ledger");
        s.setAdGeoBasis("analogized");
        s.setAdDataYear(CALC_YEAR);
        DqiSuggestionDto dto = generate(s).get(0);
        assertThat(dim(dto, "A4").getSuggested()).isEqualTo(2);
        assertThat(dim(dto, "A5").getSuggested()).isEqualTo(5);
    }

    @Test
    @DisplayName("T41/T53: record 类 A6 正常评分 → manual_ledger+quality=4 时 A6=4、a6Source=normal")
    void t41_recordA6_normalScoring() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("manual_ledger");
        s.setAdDataCollectionQuality(4);
        DqiSuggestionDto dto = generate(s).get(0);
        DqiDimSuggestionDto a6 = dim(dto, "A6");
        assertThat(a6.getSuggested()).isEqualTo(4);
        assertThat(a6.getA6Source()).isEqualTo("normal");
        // A6 与 A1 独立正交：manual_ledger → A1=4
        assertThat(dim(dto, "A1").getSuggested()).isEqualTo(4);
    }

    @Test
    @DisplayName("T40: excluded 类 A6 自动中性 → default_or_estimated 时 A6=3、a6Source=neutral_excluded")
    void t40_excludedA6_autoNeutral() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("default_or_estimated");
        s.setAdMeterCalibration("calib_not_applicable");
        s.setAdGeoBasis("allocated");
        s.setAdDataCollectionQuality(null);
        DqiSuggestionDto dto = generate(s).get(0);
        DqiDimSuggestionDto a6 = dim(dto, "A6");
        assertThat(a6.getSuggested()).isEqualTo(3);
        assertThat(a6.getA6Source()).isEqualTo("neutral_excluded");
        assertThat(a6.getStatus()).isEqualTo("complete");
        // AD 五维统一启用，不按 excluded 剔除
        for (String dimCode : List.of("A1", "A2", "A4", "A5", "A6")) {
            assertThat(dim(dto, dimCode)).isNotNull();
        }
    }

    @Test
    @DisplayName("T54: excluded 类 A6 用户填 1 提交时被强制回写 3 分并标注 neutral_excluded")
    void t54_submitScores_excludedA6ForcedBackToThree() {
        UncertaintySourceMeta meta = baseSource();
        meta.setAdMeteringTier("default_or_estimated");
        when(sourceMetaRepository.findById(SOURCE_ID)).thenReturn(Optional.of(meta));

        List<UncertaintyScore> rows = new ArrayList<>();
        int[] suggested = {1, 3, 3, 5, 3};
        String[] dims = {"A1", "A2", "A4", "A5", "A6"};
        for (int i = 0; i < dims.length; i++) {
            UncertaintyScore row = new UncertaintyScore();
            row.setId((long) (i + 1));
            row.setSourceMetaId(SOURCE_ID);
            row.setParamType("AD");
            row.setDimCode(dims[i]);
            row.setWeight(BigDecimal.ONE);
            row.setSuggestedScore(suggested[i]);
            row.setRulesetVersion(RULESET_VERSION);
            rows.add(row);
        }
        when(scoreRepository.findBySourceMetaId(SOURCE_ID)).thenReturn(rows);

        UncertaintyRuleset ruleset = ruleset();
        when(rulesetRepository.findByRulesetVersion(RULESET_VERSION)).thenReturn(Optional.of(ruleset));
        when(dimensionRuleRepository.findByRulesetIdAndAppliesTo(ruleset.getId(), "AD"))
                .thenReturn(allDimRules().stream()
                        .filter(r -> "AD".equals(r.getAppliesTo()))
                        .toList());
        when(scoreRepository.save(any())).thenAnswer(inv -> inv.getArgument(0));

        DqiScoreSubmitItem item = new DqiScoreSubmitItem();
        item.setDimCode("A6");
        item.setFinalScore(1);
        DqiScoreSubmitRequest request = new DqiScoreSubmitRequest();
        request.setItems(List.of(item));

        service.submitScores(SOURCE_ID, "AD", request, "tester");

        UncertaintyScore a6 = rows.stream()
                .filter(r -> "A6".equals(r.getDimCode()))
                .findFirst().orElseThrow();
        assertThat(a6.getFinalScore()).isEqualTo(3);
        assertThat(a6.getScoreSource()).isEqualTo("auto_neutral_excluded");
        assertThat(a6.getA6Source()).isEqualTo("neutral_excluded");
        assertThat(a6.getWarnings()).contains("系统自动覆盖为 3 分");
        verify(auditRepository).saveAll(anyList());
    }

    @Test
    @DisplayName("T13: A2 中性分策略 → calib_not_applicable 时 A2=3 且 evidence 标注不适用")
    void t13_a2Neutral_notApplicable() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("default_or_estimated");
        s.setAdMeterCalibration("calib_not_applicable");
        s.setAdGeoBasis("allocated");
        DqiSuggestionDto dto = generate(s).get(0);
        DqiDimSuggestionDto a2 = dim(dto, "A2");
        assertThat(a2.getSuggested()).isEqualTo(3);
        assertThat(a2.getEvidence()).contains("不适用");
        // 质量判断由 A1 承接：default_or_estimated → A1=1
        assertThat(dim(dto, "A1").getSuggested()).isEqualTo(1);
        // 不触发 W1（calib_not_applicable 是合法组合）
        assertThat(dim(dto, "A1").getWarnings())
                .noneMatch(w -> w.startsWith("W1"));
    }

    @Test
    @DisplayName("T26: ad_geo_basis 留空 → A4 按 direct_metered 取 5 分且 defaultFilled=true")
    void t26_geoBasisBlank_defaultFilled() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("manual_ledger");
        s.setAdGeoBasis(null);
        DqiSuggestionDto dto = generate(s).get(0);
        DqiDimSuggestionDto a4 = dim(dto, "A4");
        assertThat(a4.getSuggested()).isEqualTo(5);
        assertThat(a4.getDefaultFilled()).isTrue();
        assertThat(a4.getEvidence()).contains("默认填充");
    }

    @Test
    @DisplayName("T12: 元数据缺失回退 → record 类 quality=null 时 A6 suggested=null、状态 partial")
    void t12_missingMetadata_fallbackToManual() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("manual_ledger");
        s.setAdDataCollectionQuality(null);
        DqiSuggestionDto dto = generate(s).get(0);
        DqiDimSuggestionDto a6 = dim(dto, "A6");
        assertThat(a6.getSuggested()).isNull();
        assertThat(a6.getStatus()).isNotEqualTo("complete");
        assertThat(a6.getEvidence()).contains("ad_data_collection_quality");
        assertThat(a6.getEvidence()).contains("转人工");
        // 记录级降级：任一维度 null → 全部维度状态非 complete
        assertThat(dim(dto, "A1").getStatus()).isNotEqualTo("complete");
    }

    @Test
    @DisplayName("T36: W1 估算来源填器具状态 → default_or_estimated+cert 触发 W1，A1=1/A2=5 照常")
    void t36_w1_estimatedTierWithCalibration() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("default_or_estimated");
        s.setAdMeterCalibration("calib_valid_cert");
        s.setAdGeoBasis("allocated");
        DqiSuggestionDto dto = generate(s).get(0);
        assertThat(dim(dto, "A1").getSuggested()).isEqualTo(1);
        assertThat(dim(dto, "A2").getSuggested()).isEqualTo(5);
        assertThat(dim(dto, "A1").getWarnings())
                .anyMatch(w -> w.startsWith("W1"));
    }

    @Test
    @DisplayName("T37: W2 中性分套利防范 → online_meter+not_applicable 触发 W2，A2=3")
    void t37_w2_onlineMeterNotApplicable() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("online_meter");
        s.setAdMeterCalibration("calib_not_applicable");
        DqiSuggestionDto dto = generate(s).get(0);
        DqiDimSuggestionDto a2 = dim(dto, "A2");
        assertThat(a2.getSuggested()).isEqualTo(3);
        assertThat(a2.getWarnings()).anyMatch(w -> w.startsWith("W2"));
    }

    @Test
    @DisplayName("T23/T37-W3: 文献/估算来源+direct_metered → 触发 W3")
    void t23_w3_literatureDirectMetered() {
        UncertaintySourceMeta s = baseSource();
        s.setAdMeteringTier("literature_thirdparty");
        s.setAdMeterCalibration("calib_not_applicable");
        s.setAdGeoBasis("direct_metered");
        DqiSuggestionDto dto = generate(s).get(0);
        assertThat(dim(dto, "A4").getSuggested()).isEqualTo(5);
        assertThat(dim(dto, "A4").getWarnings())
                .anyMatch(w -> w.startsWith("W3"));
    }
}
