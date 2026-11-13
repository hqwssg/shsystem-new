package com.ruoyi.carbon.report.service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.domain.dto.ReportFactorPlan;
import com.ruoyi.carbon.report.generation.CarbonReportRendererProperties;
import com.ruoyi.carbon.report.generation.DiskArtifactStore;
import com.ruoyi.carbon.report.generation.ReportFileBytes;
import com.ruoyi.carbon.report.generation.ReportImageSlots;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;
import com.ruoyi.carbon.report.source.ReportFactorResolver;
import com.ruoyi.carbon.report.source.ReportValidator;
import com.ruoyi.common.core.utils.PythonServiceClient;

@Service
public class ReportPreflight
{
    private final CarbonReportRendererProperties properties;
    private final ReportFileMapper fileMapper;
    private final ReportFactorResolver factorResolver;

    public ReportPreflight(CarbonReportRendererProperties properties, ReportFileMapper fileMapper,
            EmissionCalculationMapper calculationMapper)
    {
        this.properties = properties;
        this.fileMapper = fileMapper;
        this.factorResolver = new ReportFactorResolver(calculationMapper);
    }

    public Map<String, Object> inspect(ReportDraft draft)
    {
        Map<String, Object> result = ReportValidator.validate(draft);
        List<String> mustFix = stringList(result.get("mustFix"));
        List<String> shouldConfirm = stringList(result.get("shouldConfirm"));
        mustFix.addAll(imageProblems(draft));
        mustFix.addAll(rendererProblems());
        ReportFactorPlan plan = factorResolver.plan(draft);
        if (!plan.isComplete())
        {
            shouldConfirm.add(factorMessage(plan));
        }
        boolean pdfReady = sofficeReady();
        if (!pdfReady)
        {
            shouldConfirm.add("本机找不到 LibreOffice，生成 PDF 会失败");
        }
        result.put("mustFix", mustFix);
        result.put("shouldConfirm", shouldConfirm);
        result.put("pdfReady", pdfReady);
        result.put("ok", mustFix.isEmpty());
        return result;
    }

    private List<String> imageProblems(ReportDraft draft)
    {
        List<String> problems = new ArrayList<>();
        if (draft == null)
        {
            return problems;
        }
        DiskArtifactStore store = new DiskArtifactStore(properties.artifactDirPath());
        for (Map<String, Object> image : ReportImageSlots.snapshotImages(draft.getImages(), draft.getDefaultImages()))
        {
            String role = String.valueOf(image.get("role"));
            String url = String.valueOf(image.get("url"));
            if (!url.startsWith(ReportImageSlots.CARBON_FILE_PREFIX))
            {
                continue;
            }
            String label = roleLabel(role);
            try
            {
                Long fileId = Long.valueOf(url.substring(ReportImageSlots.CARBON_FILE_PREFIX.length()));
                ReportFile meta = fileMapper.selectById(fileId);
                byte[] bytes = ReportFileBytes.read(meta, store, fileMapper);
                if (bytes == null || bytes.length == 0)
                {
                    problems.add(label + "已配置，但图片内容读不出来");
                }
            }
            catch (Exception ex)
            {
                problems.add(label + "图片读取失败");
            }
        }
        return problems;
    }

    private List<String> rendererProblems()
    {
        List<String> problems = new ArrayList<>();
        if (PythonServiceClient.enabled())
        {
            try
            {
                Map<String, Object> capabilities = PythonServiceClient.capabilities();
                if (!Boolean.TRUE.equals(capabilities.get("report")))
                    problems.add("Python 服务未加载报告生成模块");
                return problems;
            }
            catch (Exception ex)
            {
                problems.add("Python 报告服务不可用");
                return problems;
            }
        }
        String python = properties.getPythonExecutable();
        if (!commandExists(python))
        {
            problems.add("Word 渲染程序不存在：" + (python == null || python.isBlank() ? "未配置" : python));
        }
        Path agent = properties.moduleRootPath().resolve("carbon_report_agent").resolve("cli.py");
        if (!Files.isRegularFile(agent))
        {
            problems.add("报告渲染模块未找到，请检查报告模块目录是否指向 carbon_report_agent 的上一级");
        }
        try
        {
            Files.createDirectories(properties.workDirPath());
        }
        catch (Exception ex)
        {
            problems.add("渲染工作目录无法创建");
        }
        return problems;
    }

    private boolean sofficeReady()
    {
        if (PythonServiceClient.enabled())
        {
            try
            {
                return PythonServiceClient.capabilities().getBooleanValue("pdf");
            }
            catch (Exception ex)
            {
                return false;
            }
        }
        String configured = properties.getSofficePath();
        if (configured != null && !configured.isBlank())
        {
            return Files.isRegularFile(Path.of(configured));
        }
        return commandExists("soffice") || commandExists("soffice.com") || commandExists("libreoffice");
    }

    private static boolean commandExists(String command)
    {
        if (command == null || command.isBlank())
        {
            return false;
        }
        String trimmed = command.trim();
        boolean looksLikePath = trimmed.contains("/") || trimmed.contains("\\") || trimmed.endsWith(".exe")
                || trimmed.endsWith(".com");
        if (looksLikePath)
        {
            return Files.isRegularFile(Path.of(trimmed));
        }
        String finder = System.getProperty("os.name", "").toLowerCase().contains("win") ? "where.exe" : "which";
        try
        {
            Process process = new ProcessBuilder(finder, trimmed).redirectErrorStream(true).start();
            process.getInputStream().readAllBytes();
            return process.waitFor() == 0;
        }
        catch (Exception ex)
        {
            return false;
        }
    }

    private static String factorMessage(ReportFactorPlan plan)
    {
        String reason = plan.getReason() == null || plan.getReason().isBlank() ? "现用核算模板缺少因子" : plan.getReason();
        if (plan.getMissing() == null || plan.getMissing().isEmpty())
        {
            return reason + "。生成时可以改用系统默认因子。";
        }
        return reason + "：" + String.join("、", plan.getMissing()) + "。生成时可以改用系统默认因子。";
    }

    private static String roleLabel(String role)
    {
        if ("cover_logo".equals(role))
        {
            return "封面";
        }
        if ("org_chart".equals(role))
        {
            return "组织机构图";
        }
        if ("office_location".equals(role))
        {
            return "机关所在地";
        }
        return "报告图片";
    }

    @SuppressWarnings("unchecked")
    private static List<String> stringList(Object value)
    {
        if (value instanceof List<?> list)
        {
            List<String> copy = new ArrayList<>();
            for (Object item : list)
            {
                if (item != null)
                {
                    copy.add(String.valueOf(item));
                }
            }
            return copy;
        }
        return new ArrayList<>();
    }
}
