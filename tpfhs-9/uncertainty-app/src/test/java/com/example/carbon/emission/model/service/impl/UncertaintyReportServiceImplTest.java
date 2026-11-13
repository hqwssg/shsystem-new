package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.UncertaintyReportDto;
import com.example.carbon.emission.model.entity.UncertaintyParamResult;
import com.example.carbon.emission.model.entity.UncertaintyRun;
import com.example.carbon.emission.model.entity.UncertaintyRunScope;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.repository.UncertaintyParamResultRepository;
import com.example.carbon.emission.model.repository.UncertaintyRunRepository;
import com.example.carbon.emission.model.repository.UncertaintyRunScopeRepository;
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
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * UncertaintyReportServiceImpl 单元测试（纯 Mockito，不启动 Spring 容器）
 * <p>
 * 覆盖 O5 报告生成：运行记录不存在/非 SUCCESS 状态阻断、全量章节组装
 * （任务信息/点估计/MCS统计/O4验证/O7完整性/O1参数明细/警告集合）、
 * 分位数与警告 JSON 解析兜底、PDF 字节流生成。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("不确定性报告生成服务测试（O5/M6）")
class UncertaintyReportServiceImplTest {

    private static final Long RUN_ID = 1L;

    @Mock
    private UncertaintyRunRepository uncertaintyRunRepository;

    @Mock
    private UncertaintyRunScopeRepository uncertaintyRunScopeRepository;

    @Mock
    private UncertaintyParamResultRepository uncertaintyParamResultRepository;

    @Mock
    private UncertaintySourceMetaRepository uncertaintySourceMetaRepository;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private UncertaintyReportServiceImpl service;

    // ========================= 测试前置数据构造 =========================

    /** SUCCESS 状态完整运行记录（含分位数与警告 JSON） */
    private UncertaintyRun successRun() {
        UncertaintyRun run = new UncertaintyRun();
        run.setId(RUN_ID);
        run.setCalculationTemplateId(100L);
        run.setRulesetVersion("DQI-RULES-2026.12");
        run.setNIterations(10000);
        run.setConfidenceLevel(new BigDecimal("0.950"));
        run.setRandomSeed(42L);
        run.setCompletenessScopeLevel("scope");
        run.setStatus("SUCCESS");
        run.setEPointRaw(new BigDecimal("1000.00000000"));
        run.setEPointCov(new BigDecimal("1010.00000000"));
        run.setUpliftPercent(new BigDecimal("1.000000"));
        run.setTotalMean(new BigDecimal("1010.100000"));
        run.setTotalMedian(new BigDecimal("1010.050000"));
        run.setTotalStd(new BigDecimal("80.000000"));
        run.setCvPercent(new BigDecimal("7.9200"));
        run.setCiLower(new BigDecimal("850.00000000"));
        run.setCiUpper(new BigDecimal("1170.00000000"));
        run.setQuantiles("{\"p5\":880.1,\"p25\":960.2,\"p50\":1010.05,\"p75\":1060.3,\"p95\":1140.4}");
        run.setDevMeanPercent(new BigDecimal("0.0099"));
        run.setDevMedianPercent(new BigDecimal("0.0050"));
        run.setPointCovInCi(true);
        run.setRawLeCov(true);
        run.setUncertaintyLevel("中");
        run.setVerificationConclusion("经完整性修正后排放量为 E_point_cov=1010.0……");
        run.setWarnings("[\"W15: Scope scope2 无独立基准\",\"W01: 测试警告\"]");
        run.setStartedAt(LocalDateTime.of(2026, 10, 17, 10, 0, 0));
        run.setFinishedAt(LocalDateTime.of(2026, 10, 17, 10, 0, 5));
        return run;
    }

    private UncertaintyRunScope scopeRow() {
        UncertaintyRunScope row = new UncertaintyRunScope();
        row.setRunId(RUN_ID);
        row.setScope("scope2");
        row.setScopeEmission(new BigDecimal("600"));
        row.setBasis("measured");
        row.setRMeasured(new BigDecimal("0.900000"));
        row.setDeltaCovPercent(new BigDecimal("12"));
        row.setEXiCov(new BigDecimal("1.007500"));
        return row;
    }

    private UncertaintyParamResult paramRow() {
        UncertaintyParamResult row = new UncertaintyParamResult();
        row.setRunId(RUN_ID);
        row.setSourceMetaId(11L);
        row.setParamType("AD");
        row.setRulesetVersion("DQI-RULES-2026.12");
        row.setSumQW(new BigDecimal("4.000"));
        row.setSumQMinW(new BigDecimal("1.000"));
        row.setSumQMaxW(new BigDecimal("5.000"));
        row.setXPercent(new BigDecimal("80.0000"));
        row.setSdqi(new BigDecimal("4.0"));
        row.setBetaAlpha(new BigDecimal("16.0000"));
        row.setBetaBeta(new BigDecimal("16.0000"));
        row.setDeltaPercent(new BigDecimal("5.0000"));
        row.setSupportLowFactor(new BigDecimal("0.95000"));
        row.setSupportHighFactor(new BigDecimal("1.05000"));
        row.setWarnings("W01");
        return row;
    }

    /** 装配 SUCCESS 场景全部 mock（运行记录 + scope + 参数 + 源名称） */
    private void stubSuccessScene(UncertaintyRun run) {
        when(uncertaintyRunRepository.findById(RUN_ID)).thenReturn(Optional.of(run));
        when(uncertaintyRunScopeRepository.findByRunId(RUN_ID)).thenReturn(List.of(scopeRow()));
        when(uncertaintyParamResultRepository.findByRunId(RUN_ID)).thenReturn(List.of(paramRow()));
        UncertaintySourceMeta meta = new UncertaintySourceMeta();
        meta.setId(11L);
        meta.setSourceName("燃煤锅炉");
        when(uncertaintySourceMetaRepository.findAllById(any())).thenReturn(List.of(meta));
    }

    // ========================= 用例 =========================

    @Test
    @DisplayName("运行记录不存在 → IllegalArgumentException")
    void runNotFound() {
        when(uncertaintyRunRepository.findById(RUN_ID)).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.getReport(RUN_ID))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("模拟运行记录不存在");
    }

    @Test
    @DisplayName("RUNNING 状态 → IllegalStateException，禁止生成报告")
    void runningStatusRejected() {
        UncertaintyRun run = successRun();
        run.setStatus("RUNNING");
        when(uncertaintyRunRepository.findById(RUN_ID)).thenReturn(Optional.of(run));
        assertThatThrownBy(() -> service.getReport(RUN_ID))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("未成功完成");
    }

    @Test
    @DisplayName("FAILED 状态 → IllegalStateException，禁止生成报告")
    void failedStatusRejected() {
        UncertaintyRun run = successRun();
        run.setStatus("FAILED");
        when(uncertaintyRunRepository.findById(RUN_ID)).thenReturn(Optional.of(run));
        assertThatThrownBy(() -> service.getReport(RUN_ID))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("未成功完成");
    }

    @Test
    @DisplayName("SUCCESS → 全量章节组装：配置快照/点估计/MCS统计/O4/O7/O1/警告")
    void successAssemblesAllSections() {
        stubSuccessScene(successRun());

        UncertaintyReportDto report = service.getReport(RUN_ID);

        assertThat(report.getGeneratedAt()).isNotNull();

        // 任务信息与配置快照
        UncertaintyReportDto.TaskInfoSection ti = report.getTaskInfo();
        assertThat(ti.getRunId()).isEqualTo(RUN_ID);
        assertThat(ti.getCalculationTemplateId()).isEqualTo(100L);
        assertThat(ti.getStatus()).isEqualTo("SUCCESS");
        assertThat(ti.getRulesetVersion()).isEqualTo("DQI-RULES-2026.12");
        assertThat(ti.getNIterations()).isEqualTo(10000);
        assertThat(ti.getConfidenceLevel()).isEqualByComparingTo("0.950");
        assertThat(ti.getRandomSeed()).isEqualTo(42L);
        assertThat(ti.getCompletenessScopeLevel()).isEqualTo("scope");
        assertThat(ti.getStartedAt()).isEqualTo(LocalDateTime.of(2026, 10, 17, 10, 0, 0));
        assertThat(ti.getFinishedAt()).isEqualTo(LocalDateTime.of(2026, 10, 17, 10, 0, 5));

        // 点估计与上抬
        assertThat(report.getPointEstimate().getEPointRaw()).isEqualByComparingTo("1000.00000000");
        assertThat(report.getPointEstimate().getEPointCov()).isEqualByComparingTo("1010.00000000");
        assertThat(report.getPointEstimate().getUpliftPercent()).isEqualByComparingTo("1.000000");

        // MCS 统计量与置信区间（分位数 JSON 反序列化保序）
        UncertaintyReportDto.McsStatisticsSection ms = report.getMcsStatistics();
        assertThat(ms.getTotalMean()).isEqualByComparingTo("1010.100000");
        assertThat(ms.getCiLower()).isEqualByComparingTo("850.00000000");
        assertThat(ms.getCiUpper()).isEqualByComparingTo("1170.00000000");
        assertThat(ms.getQuantiles()).containsExactly(
                Map.entry("p5", 880.1), Map.entry("p25", 960.2), Map.entry("p50", 1010.05),
                Map.entry("p75", 1060.3), Map.entry("p95", 1140.4));

        // 无偏性验证与不确定性等级（O4）
        UncertaintyReportDto.VerificationSection v = report.getVerification();
        assertThat(v.getDevMeanPercent()).isEqualByComparingTo("0.0099");
        assertThat(v.getPointCovInCi()).isTrue();
        assertThat(v.getRawLeCov()).isTrue();
        assertThat(v.getUncertaintyLevel()).isEqualTo("中");
        assertThat(v.getVerificationConclusion()).contains("E_point_cov");

        // Scope 级完整性披露（O7）
        assertThat(report.getScopeCompleteness()).hasSize(1);
        UncertaintyReportDto.ScopeCompletenessSection s = report.getScopeCompleteness().get(0);
        assertThat(s.getScope()).isEqualTo("scope2");
        assertThat(s.getBasis()).isEqualTo("measured");
        assertThat(s.getRMeasured()).isEqualByComparingTo("0.900000");
        assertThat(s.getEXiCov()).isEqualByComparingTo("1.007500");

        // 参数级明细（O1，关联排放源名称）
        assertThat(report.getParamDetails()).hasSize(1);
        UncertaintyReportDto.ParamDetailSection p = report.getParamDetails().get(0);
        assertThat(p.getSourceMetaId()).isEqualTo(11L);
        assertThat(p.getSourceName()).isEqualTo("燃煤锅炉");
        assertThat(p.getParamType()).isEqualTo("AD");
        assertThat(p.getSdqi()).isEqualByComparingTo("4.0");
        assertThat(p.getBetaAlpha()).isEqualByComparingTo("16.0000");
        assertThat(p.getWarnings()).isEqualTo("W01");

        // 警告集合
        assertThat(report.getWarnings()).containsExactly("W15: Scope scope2 无独立基准", "W01: 测试警告");
    }

    @Test
    @DisplayName("分位数/警告为 null → 空 Map/空 List 兜底，不报错")
    void nullQuantilesAndWarningsFallback() {
        UncertaintyRun run = successRun();
        run.setQuantiles(null);
        run.setWarnings(null);
        stubSuccessScene(run);

        UncertaintyReportDto report = service.getReport(RUN_ID);
        assertThat(report.getMcsStatistics().getQuantiles()).isEmpty();
        assertThat(report.getWarnings()).isEmpty();
    }

    @Test
    @DisplayName("分位数非法 JSON → 空 Map 兜底，不报错")
    void invalidQuantilesJsonFallback() {
        UncertaintyRun run = successRun();
        run.setQuantiles("not-json");
        stubSuccessScene(run);

        UncertaintyReportDto report = service.getReport(RUN_ID);
        assertThat(report.getMcsStatistics().getQuantiles()).isEmpty();
    }

    @Test
    @DisplayName("PDF 生成 → 返回以 %PDF 开头的非空字节流")
    void pdfGenerated() {
        stubSuccessScene(successRun());

        byte[] pdf = service.getReportPdf(RUN_ID);

        assertThat(pdf).isNotNull();
        assertThat(pdf.length).isGreaterThan(500);
        assertThat(new String(pdf, 0, 4)).isEqualTo("%PDF");
    }
}
