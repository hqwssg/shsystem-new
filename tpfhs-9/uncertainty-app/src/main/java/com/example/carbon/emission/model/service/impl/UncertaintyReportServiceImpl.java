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
import com.example.carbon.emission.model.service.UncertaintyReportService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lowagie.text.Document;
import com.lowagie.text.Element;
import com.lowagie.text.Font;
import com.lowagie.text.PageSize;
import com.lowagie.text.Paragraph;
import com.lowagie.text.Phrase;
import com.lowagie.text.pdf.BaseFont;
import com.lowagie.text.pdf.PdfPCell;
import com.lowagie.text.pdf.PdfPTable;
import com.lowagie.text.pdf.PdfWriter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.awt.Color;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 不确定性分析报告生成 Service 实现（O5）
 * <p>
 * 报告数据全部来自 M3-M5 落库结果（uncertainty_run / uncertainty_run_scope /
 * uncertainty_param_result），仅做聚合与展示，不重新计算。
 * PDF 使用 OpenPDF 渲染，中文字体采用 STSong-Light（UniGB-UCS2-H 编码）。
 */
@Service
public class UncertaintyReportServiceImpl implements UncertaintyReportService {

    private static final Logger log = LoggerFactory.getLogger(UncertaintyReportServiceImpl.class);

    /**
     * 可生成报告的唯一运行状态
     */
    private static final String STATUS_SUCCESS = "SUCCESS";

    /**
     * PDF 时间格式
     */
    private static final DateTimeFormatter TIME_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    /**
     * 模拟运行 Repository
     */
    @Autowired
    private UncertaintyRunRepository uncertaintyRunRepository;

    /**
     * Scope 级完整性评估 Repository
     */
    @Autowired
    private UncertaintyRunScopeRepository uncertaintyRunScopeRepository;

    /**
     * 参数级结果 Repository
     */
    @Autowired
    private UncertaintyParamResultRepository uncertaintyParamResultRepository;

    /**
     * 排放源元信息 Repository（参数明细展示源名称）
     */
    @Autowired
    private UncertaintySourceMetaRepository uncertaintySourceMetaRepository;

    /**
     * JSON 解析器（分位数与警告反序列化）
     */
    @Autowired
    private ObjectMapper objectMapper;

    @Override
    public UncertaintyReportDto getReport(Long runId) {
        if (runId == null) {
            throw new IllegalArgumentException("运行ID不能为空");
        }
        UncertaintyRun run = uncertaintyRunRepository.findById(runId)
                .orElseThrow(() -> new IllegalArgumentException("模拟运行记录不存在：id=" + runId));
        if (!STATUS_SUCCESS.equals(run.getStatus())) {
            throw new IllegalStateException("模拟运行未成功完成，无法生成报告：runId=" + runId
                    + "，status=" + run.getStatus());
        }

        List<UncertaintyRunScope> scopes = uncertaintyRunScopeRepository.findByRunId(runId);
        List<UncertaintyParamResult> params = uncertaintyParamResultRepository.findByRunId(runId);

        // 排放源名称索引（参数明细展示用）
        List<Long> sourceMetaIds = params.stream()
                .map(UncertaintyParamResult::getSourceMetaId).distinct().collect(Collectors.toList());
        Map<Long, String> sourceNames = sourceMetaIds.isEmpty()
                ? Map.of()
                : uncertaintySourceMetaRepository.findAllById(sourceMetaIds).stream()
                        .collect(Collectors.toMap(UncertaintySourceMeta::getId, UncertaintySourceMeta::getSourceName));

        UncertaintyReportDto report = new UncertaintyReportDto();
        report.setGeneratedAt(LocalDateTime.now());
        report.setTaskInfo(buildTaskInfo(run));
        report.setPointEstimate(buildPointEstimate(run));
        report.setMcsStatistics(buildMcsStatistics(run));
        report.setVerification(buildVerification(run));
        report.setScopeCompleteness(scopes.stream().map(this::toScopeSection).collect(Collectors.toList()));
        report.setParamDetails(params.stream()
                .map(param -> toParamSection(param, sourceNames.get(param.getSourceMetaId())))
                .collect(Collectors.toList()));
        report.setWarnings(parseWarnings(run.getWarnings()));
        return report;
    }

    @Override
    public byte[] getReportPdf(Long runId) {
        UncertaintyReportDto report = getReport(runId);
        try {
            return renderPdf(report);
        } catch (Exception e) {
            throw new RuntimeException("PDF报告生成失败：" + e.getMessage(), e);
        }
    }

    // ============================== 章节组装 ==============================

    /**
     * 任务信息与配置快照章节
     */
    private UncertaintyReportDto.TaskInfoSection buildTaskInfo(UncertaintyRun run) {
        UncertaintyReportDto.TaskInfoSection section = new UncertaintyReportDto.TaskInfoSection();
        section.setRunId(run.getId());
        section.setCalculationTemplateId(run.getCalculationTemplateId());
        section.setStatus(run.getStatus());
        section.setRulesetVersion(run.getRulesetVersion());
        section.setNIterations(run.getNIterations());
        section.setConfidenceLevel(run.getConfidenceLevel());
        section.setRandomSeed(run.getRandomSeed());
        section.setCompletenessScopeLevel(run.getCompletenessScopeLevel());
        section.setStartedAt(run.getStartedAt());
        section.setFinishedAt(run.getFinishedAt());
        return section;
    }

    /**
     * 点估计与上抬章节
     */
    private UncertaintyReportDto.PointEstimateSection buildPointEstimate(UncertaintyRun run) {
        UncertaintyReportDto.PointEstimateSection section = new UncertaintyReportDto.PointEstimateSection();
        section.setEPointRaw(run.getEPointRaw());
        section.setEPointCov(run.getEPointCov());
        section.setUpliftPercent(run.getUpliftPercent());
        return section;
    }

    /**
     * MCS 统计量与置信区间章节（分位数 JSON 反序列化，异常时按空集兜底）
     */
    private UncertaintyReportDto.McsStatisticsSection buildMcsStatistics(UncertaintyRun run) {
        UncertaintyReportDto.McsStatisticsSection section = new UncertaintyReportDto.McsStatisticsSection();
        section.setTotalMean(run.getTotalMean());
        section.setTotalMedian(run.getTotalMedian());
        section.setTotalStd(run.getTotalStd());
        section.setCvPercent(run.getCvPercent());
        section.setCiLower(run.getCiLower());
        section.setCiUpper(run.getCiUpper());
        section.setQuantiles(parseQuantiles(run.getQuantiles()));
        return section;
    }

    /**
     * 无偏性验证与不确定性等级章节（O4）
     */
    private UncertaintyReportDto.VerificationSection buildVerification(UncertaintyRun run) {
        UncertaintyReportDto.VerificationSection section = new UncertaintyReportDto.VerificationSection();
        section.setDevMeanPercent(run.getDevMeanPercent());
        section.setDevMedianPercent(run.getDevMedianPercent());
        section.setPointCovInCi(run.getPointCovInCi());
        section.setRawLeCov(run.getRawLeCov());
        section.setUncertaintyLevel(run.getUncertaintyLevel());
        section.setVerificationConclusion(run.getVerificationConclusion());
        return section;
    }

    /**
     * Scope 级完整性披露章节行（O7）
     */
    private UncertaintyReportDto.ScopeCompletenessSection toScopeSection(UncertaintyRunScope scope) {
        UncertaintyReportDto.ScopeCompletenessSection section = new UncertaintyReportDto.ScopeCompletenessSection();
        section.setScope(scope.getScope());
        section.setScopeEmission(scope.getScopeEmission());
        section.setBasis(scope.getBasis());
        section.setBenchmarkQty(scope.getBenchmarkQty());
        section.setBenchmarkSource(scope.getBenchmarkSource());
        section.setRBenchmark(scope.getRBenchmark());
        section.setRMeasured(scope.getRMeasured());
        section.setPointRatioXn(scope.getPointRatioXn());
        section.setDeltaCovPercent(scope.getDeltaCovPercent());
        section.setEXiCov(scope.getEXiCov());
        section.setDisclosure(scope.getDisclosure());
        return section;
    }

    /**
     * 参数级明细章节行（O1，关联排放源名称）
     */
    private UncertaintyReportDto.ParamDetailSection toParamSection(UncertaintyParamResult param, String sourceName) {
        UncertaintyReportDto.ParamDetailSection section = new UncertaintyReportDto.ParamDetailSection();
        section.setSourceMetaId(param.getSourceMetaId());
        section.setSourceName(sourceName);
        section.setParamType(param.getParamType());
        section.setRulesetVersion(param.getRulesetVersion());
        section.setSumQW(param.getSumQW());
        section.setSumQMinW(param.getSumQMinW());
        section.setSumQMaxW(param.getSumQMaxW());
        section.setXPercent(param.getXPercent());
        section.setSdqi(param.getSdqi());
        section.setBetaAlpha(param.getBetaAlpha());
        section.setBetaBeta(param.getBetaBeta());
        section.setDeltaPercent(param.getDeltaPercent());
        section.setSupportLowFactor(param.getSupportLowFactor());
        section.setSupportHighFactor(param.getSupportHighFactor());
        section.setWarnings(param.getWarnings());
        return section;
    }

    /**
     * 分位数 JSON 反序列化（保持 p5→p95 顺序；空值或非法 JSON 按空集兜底）
     */
    private Map<String, Double> parseQuantiles(String json) {
        if (json == null || json.isBlank()) {
            return new LinkedHashMap<>();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<LinkedHashMap<String, Double>>() {
            });
        } catch (Exception e) {
            log.warn("分位数JSON解析失败，按空集返回：{}", e.getMessage());
            return new LinkedHashMap<>();
        }
    }

    /**
     * 警告集合 JSON 反序列化（空值或非法 JSON 按空集兜底）
     */
    private List<String> parseWarnings(String json) {
        if (json == null || json.isBlank()) {
            return new ArrayList<>();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<String>>() {
            });
        } catch (Exception e) {
            log.warn("警告集合JSON解析失败，按空集返回：{}", e.getMessage());
            return new ArrayList<>();
        }
    }

    // ============================== PDF 渲染 ==============================

    /** 章节标题上方留白（pt） */
    private static final float SECTION_SPACING_BEFORE = 12f;
    /** 章节标题下方留白（pt） */
    private static final float SECTION_SPACING_AFTER = 6f;
    /** 表格上方留白（pt） */
    private static final float TABLE_SPACING_BEFORE = 4f;
    /** 表格下方留白（pt） */
    private static final float TABLE_SPACING_AFTER = 4f;
    /** 单元格内边距（pt） */
    private static final float CELL_PADDING = 4f;

    /**
     * 构造带上下留白的章节标题段落
     */
    private Paragraph sectionHeading(String text, Font font) {
        Paragraph p = new Paragraph(text, font);
        p.setSpacingBefore(SECTION_SPACING_BEFORE);
        p.setSpacingAfter(SECTION_SPACING_AFTER);
        p.setLeading(font.getSize() * 1.4f);
        return p;
    }

    /**
     * 给表格设置上下留白并统一单元格内边距
     */
    private void prepareTable(PdfPTable table) {
        table.setSpacingBefore(TABLE_SPACING_BEFORE);
        table.setSpacingAfter(TABLE_SPACING_AFTER);
        table.getDefaultCell().setPadding(CELL_PADDING);
    }

    /**
     * 渲染 PDF 报告（A4 横向，容纳宽表格）
     */
    private byte[] renderPdf(UncertaintyReportDto report) throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        Document document = new Document(PageSize.A4.rotate(), 36, 36, 42, 42);
        PdfWriter.getInstance(document, baos);
        document.open();

        BaseFont bf = BaseFont.createFont("STSong-Light", "UniGB-UCS2-H", BaseFont.NOT_EMBEDDED);
        Font titleFont = new Font(bf, 16, Font.BOLD);
        Font sectionFont = new Font(bf, 12, Font.BOLD);
        Font textFont = new Font(bf, 9);
        Font tableFont = new Font(bf, 8);

        // 标题
        Paragraph title = new Paragraph("碳排放数据不确定性分析报告（DQI+MCS）", titleFont);
        title.setAlignment(Element.ALIGN_CENTER);
        title.setSpacingAfter(6f);
        document.add(title);
        Paragraph subtitle = new Paragraph("生成时间：" + fmtTime(report.getGeneratedAt())
                + "    运行ID：" + report.getTaskInfo().getRunId(), textFont);
        subtitle.setAlignment(Element.ALIGN_CENTER);
        subtitle.setSpacingAfter(12f);
        document.add(subtitle);

        // 一、任务信息与配置快照
        document.add(sectionHeading("一、任务信息与配置快照", sectionFont));
        UncertaintyReportDto.TaskInfoSection ti = report.getTaskInfo();
        PdfPTable t1 = new PdfPTable(4);
        t1.setWidthPercentage(100);
        t1.setWidths(new float[]{1, 3, 1, 3});
        prepareTable(t1);
        addKvRow(t1, "核算任务ID", str(ti.getCalculationTemplateId()), "运行状态", ti.getStatus(), tableFont);
        addKvRow(t1, "规则库版本", ti.getRulesetVersion(), "迭代次数", str(ti.getNIterations()), tableFont);
        addKvRow(t1, "置信水平", fmt(ti.getConfidenceLevel()), "随机种子", str(ti.getRandomSeed()), tableFont);
        addKvRow(t1, "完整性作用范围", ti.getCompletenessScopeLevel(), "开始时间", fmtTime(ti.getStartedAt()), tableFont);
        addKvRow(t1, "完成时间", fmtTime(ti.getFinishedAt()), "", "", tableFont);
        document.add(t1);

        // 二、点估计与上抬
        document.add(sectionHeading("二、点估计与上抬", sectionFont));
        UncertaintyReportDto.PointEstimateSection pe = report.getPointEstimate();
        PdfPTable t2 = new PdfPTable(3);
        t2.setWidthPercentage(100);
        prepareTable(t2);
        addHeaderRow(t2, tableFont, "记录下锚点估计 E_point_raw", "完整性修正后点估计 E_point_cov", "上抬百分比 uplift(%)");
        addCellRow(t2, tableFont, fmt(pe.getEPointRaw()), fmt(pe.getEPointCov()), fmt(pe.getUpliftPercent()));
        document.add(t2);

        // 三、MCS 统计量与置信区间
        document.add(sectionHeading("三、MCS 统计量与置信区间", sectionFont));
        UncertaintyReportDto.McsStatisticsSection ms = report.getMcsStatistics();
        PdfPTable t3 = new PdfPTable(6);
        t3.setWidthPercentage(100);
        prepareTable(t3);
        addHeaderRow(t3, tableFont, "样本均值 μ_E", "样本中位数", "样本标准差 σ_E",
                "变异系数 CV(%)", "置信区间下界", "置信区间上界");
        addCellRow(t3, tableFont, fmt(ms.getTotalMean()), fmt(ms.getTotalMedian()), fmt(ms.getTotalStd()),
                fmt(ms.getCvPercent()), fmt(ms.getCiLower()), fmt(ms.getCiUpper()));
        document.add(t3);
        if (ms.getQuantiles() != null && !ms.getQuantiles().isEmpty()) {
            Paragraph quantLabel = new Paragraph("分位数集合：", textFont);
            quantLabel.setSpacingBefore(4f);
            quantLabel.setSpacingAfter(2f);
            document.add(quantLabel);
            PdfPTable tq = new PdfPTable(ms.getQuantiles().size());
            tq.setWidthPercentage(50);
            prepareTable(tq);
            addHeaderRow(tq, tableFont, ms.getQuantiles().keySet().toArray(new String[0]));
            List<String> values = new ArrayList<>();
            for (Double value : ms.getQuantiles().values()) {
                values.add(value == null ? "—" : String.format(Locale.ROOT, "%.6f", value));
            }
            addCellRow(tq, tableFont, values.toArray(new String[0]));
            document.add(tq);
        }

        // 四、无偏性验证与不确定性等级（O4）
        document.add(sectionHeading("四、无偏性验证与不确定性等级（O4）", sectionFont));
        UncertaintyReportDto.VerificationSection v = report.getVerification();
        PdfPTable t4 = new PdfPTable(5);
        t4.setWidthPercentage(100);
        prepareTable(t4);
        addHeaderRow(t4, tableFont, "均值偏差 dev_mean(%)", "中位数偏差 dev_median(%)",
                "E_point_cov 落入CI", "下锚关系 raw≤cov", "不确定性等级");
        addCellRow(t4, tableFont, fmt(v.getDevMeanPercent()), fmt(v.getDevMedianPercent()),
                yn(v.getPointCovInCi()), yn(v.getRawLeCov()), v.getUncertaintyLevel());
        document.add(t4);
        if (v.getVerificationConclusion() != null && !v.getVerificationConclusion().isBlank()) {
            Paragraph conclusion = new Paragraph("验证结论：" + v.getVerificationConclusion(), textFont);
            conclusion.setSpacingBefore(4f);
            document.add(conclusion);
        }

        // 五、Scope 级完整性披露（O7）
        document.add(sectionHeading("五、Scope 级完整性披露（O7）", sectionFont));
        PdfPTable t5 = new PdfPTable(11);
        t5.setWidthPercentage(100);
        prepareTable(t5);
        addHeaderRow(t5, tableFont, "Scope", "排放量E[g]", "判据", "基准量", "基准来源",
                "r_benchmark", "r_measured", "点数比x/n", "δ_cov(%)", "E[ξ_cov]", "强制披露");
        for (UncertaintyReportDto.ScopeCompletenessSection s : report.getScopeCompleteness()) {
            addCellRow(t5, tableFont, s.getScope(), fmt(s.getScopeEmission()), basisLabel(s.getBasis()),
                    fmt(s.getBenchmarkQty()), dash(s.getBenchmarkSource()), fmt(s.getRBenchmark()),
                    fmt(s.getRMeasured()), fmt(s.getPointRatioXn()), fmt(s.getDeltaCovPercent()),
                    fmt(s.getEXiCov()), dash(s.getDisclosure()));
        }
        document.add(t5);

        // 六、参数级归一化与分布参数明细（O1）
        document.add(sectionHeading("六、参数级归一化与分布参数明细（O1）", sectionFont));
        PdfPTable t6 = new PdfPTable(12);
        t6.setWidthPercentage(100);
        prepareTable(t6);
        addHeaderRow(t6, tableFont, "排放源", "参数类型", "∑Q_w", "∑Qmin_w", "∑Qmax_w", "x(%)",
                "SDQI", "α", "β", "δ(%)", "支撑区间", "警告");
        for (UncertaintyReportDto.ParamDetailSection p : report.getParamDetails()) {
            addCellRow(t6, tableFont,
                    p.getSourceName() != null ? p.getSourceName() : str(p.getSourceMetaId()),
                    p.getParamType(), fmt(p.getSumQW()), fmt(p.getSumQMinW()), fmt(p.getSumQMaxW()),
                    fmt(p.getXPercent()), fmt(p.getSdqi()), fmt(p.getBetaAlpha()), fmt(p.getBetaBeta()),
                    fmt(p.getDeltaPercent()),
                    "[" + fmt(p.getSupportLowFactor()) + ", " + fmt(p.getSupportHighFactor()) + "]",
                    dash(p.getWarnings()));
        }
        document.add(t6);

        // 七、警告集合
        document.add(sectionHeading("七、警告集合", sectionFont));
        if (report.getWarnings() == null || report.getWarnings().isEmpty()) {
            Paragraph p = new Paragraph("本次运行未触发任何警告。", textFont);
            p.setSpacingBefore(4f);
            document.add(p);
        } else {
            int index = 1;
            for (String warning : report.getWarnings()) {
                Paragraph wp = new Paragraph(index++ + ". " + warning, textFont);
                wp.setLeading(textFont.getSize() * 1.3f);
                document.add(wp);
            }
        }

        document.close();
        return baos.toByteArray();
    }

    /**
     * 键值对行（四列：键1、值1、键2、值2）
     */
    private void addKvRow(PdfPTable table, String key1, String value1, String key2, String value2, Font font) {
        table.addCell(new Phrase(key1, font));
        table.addCell(new Phrase(dash(value1), font));
        table.addCell(new Phrase(key2, font));
        table.addCell(new Phrase(dash(value2), font));
    }

    /**
     * 表头行（灰底居中，单元格内边距由 prepareTable 设置的默认 cell 提供）
     */
    private void addHeaderRow(PdfPTable table, Font font, String... headers) {
        for (String header : headers) {
            PdfPCell cell = new PdfPCell(new Phrase(header, font));
            cell.setBackgroundColor(Color.LIGHT_GRAY);
            cell.setHorizontalAlignment(Element.ALIGN_CENTER);
            cell.setPadding(CELL_PADDING);
            table.addCell(cell);
        }
    }

    /**
     * 数据行（空值显示为"—"）
     */
    private void addCellRow(PdfPTable table, Font font, String... values) {
        for (String value : values) {
            table.addCell(new Phrase(dash(value), font));
        }
    }

    /**
     * BigDecimal 展示：去尾零的十进制串，null 显示"—"
     */
    private String fmt(BigDecimal value) {
        return value == null ? "—" : value.stripTrailingZeros().toPlainString();
    }

    /**
     * 字符串展示：null/空白显示"—"
     */
    private String dash(String value) {
        return value == null || value.isBlank() ? "—" : value;
    }

    /**
     * 对象转字符串：null 显示"—"
     */
    private String str(Object value) {
        return value == null ? "—" : String.valueOf(value);
    }

    /**
     * 时间展示
     */
    private String fmtTime(LocalDateTime time) {
        return time == null ? "—" : TIME_FORMAT.format(time);
    }

    /**
     * 布尔展示：是/否
     */
    private String yn(Boolean value) {
        return value == null ? "—" : (value ? "是" : "否");
    }

    /**
     * 完整性判据中文标签
     */
    private String basisLabel(String basis) {
        if (basis == null) {
            return "—";
        }
        return switch (basis) {
            case "benchmark_measured" -> "基准+计量";
            case "measured" -> "仅计量";
            case "disabled" -> "未启用";
            default -> basis;
        };
    }
}
