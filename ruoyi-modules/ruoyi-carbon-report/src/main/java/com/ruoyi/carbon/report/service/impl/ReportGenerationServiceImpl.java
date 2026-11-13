package com.ruoyi.carbon.report.service.impl;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Map;
import java.util.concurrent.Executor;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.ReportGenerationJob;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.domain.dto.ReportFactorPlan;
import com.ruoyi.carbon.report.generation.CarbonReportRendererProperties;
import com.ruoyi.carbon.report.generation.DiskArtifactStore;
import com.ruoyi.carbon.report.generation.RenderPlan;
import com.ruoyi.carbon.report.generation.ReportFileBytes;
import com.ruoyi.carbon.report.generation.RenderResult;
import com.ruoyi.carbon.report.generation.ReportRenderer;
import com.ruoyi.carbon.report.generation.LlmRuntimeConfig;
import com.ruoyi.carbon.report.generation.ReportSnapshotAssembler;
import com.ruoyi.carbon.report.generation.SnapshotHasher;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptProfileMapper;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;
import com.ruoyi.carbon.report.mapper.ReportGenerationJobMapper;
import com.ruoyi.carbon.report.service.IReportGenerationService;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.carbon.report.service.ReportAccessGuard;
import com.ruoyi.carbon.report.source.ReportFactorResolver;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class ReportGenerationServiceImpl implements IReportGenerationService
{
    private final ReportSnapshotAssembler assembler = new ReportSnapshotAssembler();
    private final ReportFactorResolver factorResolver;
    private final IReportTaskService reportTaskService;
    private final ReportDeptProfileMapper profileMapper;
    private final ReportGenerationJobMapper jobMapper;
    private final ReportFileMapper fileMapper;
    private final ReportRenderer reportRenderer;
    private final CarbonReportRendererProperties properties;
    private final Executor executor;
    private final DiskArtifactStore artifacts;
    private final EmissionCalculationMapper calculationMapper;

    public ReportGenerationServiceImpl(
            IReportTaskService reportTaskService,
            ReportDeptProfileMapper profileMapper,
            ReportGenerationJobMapper jobMapper,
            ReportFileMapper fileMapper,
            ReportRenderer reportRenderer,
            CarbonReportRendererProperties properties,
            EmissionCalculationMapper calculationMapper,
            @Qualifier("carbonReportExecutor") Executor executor)
    {
        this.reportTaskService = reportTaskService;
        this.profileMapper = profileMapper;
        this.jobMapper = jobMapper;
        this.fileMapper = fileMapper;
        this.reportRenderer = reportRenderer;
        this.properties = properties;
        this.factorResolver = new ReportFactorResolver(calculationMapper);
        this.executor = executor;
        this.artifacts = new DiskArtifactStore(properties.artifactDirPath());
        this.calculationMapper = calculationMapper;
    }

    @Override
    public ReportFactorPlan factorPlan(Long reportId, Long deptId)
    {
        return factorResolver.plan(reportTaskService.getDraft(reportId, deptId));
    }

    @Override
    public ReportGenerationJob create(Long reportId, Long deptId, String outputKind, boolean aiEnabled, boolean useDefaultFactors)
    {
        return create(reportId, deptId, outputKind, aiEnabled, useDefaultFactors, null);
    }

    @Override
    public ReportGenerationJob create(Long reportId, Long deptId, String outputKind, boolean aiEnabled,
            boolean useDefaultFactors, LlmRuntimeConfig llmConfig)
    {
        ReportDraft draft = reportTaskService.getDraft(reportId, deptId);
        com.alibaba.fastjson2.JSONObject period = com.ruoyi.carbon.report.source.ReportPeriodSnapshot.saved(draft.getTask());
        if (period != null && "CALCULATION".equals(period.getString("mode"))) {
            var source = calculationMapper.selectTask(draft.getTask().getCalculationTemplateId());
            com.ruoyi.carbon.report.source.ReportPeriodSnapshot.requireSelection(draft.getTask(), draft.getTask().getCalculationTemplateId(), source);
            var eligible = calculationMapper.selectCompanyCandidates(deptId, draft.getTask().getPeriodStart(), draft.getTask().getPeriodEnd());
            if (eligible == null || eligible.stream().noneMatch(c -> c.isSuccess() && draft.getTask().getCalculationTemplateId().equals(c.getId())))
                throw new ServiceException("核算来源不再满足该公司正式模板成功任务条件，请核对后重新创建报告", 409);
            String current = com.ruoyi.carbon.report.source.ReportPeriodSnapshot.sourceSignature(
                    calculationMapper.selectNodeData(draft.getTask().getCalculationTemplateId()));
            if (!current.equals(period.getString("sourceSignature")))
                throw new ServiceException("核算来源已变化，请重新预览并确认带入；已有填报已保留", 409);
        }
        java.util.List<?> problems = (java.util.List<?>) com.ruoyi.carbon.report.source.ReportValidator.validate(draft).get("mustFix");
        if (!problems.isEmpty()) throw new ServiceException("生成前请修复：" + problems.stream().map(String::valueOf).collect(java.util.stream.Collectors.joining("；")), HttpStatus.BAD_REQUEST);
        ReportFactorPlan plan = factorResolver.plan(draft);
        if (!plan.isComplete() && !useDefaultFactors)
        {
            throw new ServiceException(missingMessage(plan), HttpStatus.BAD_REQUEST);
        }
        Map<String, Object> factors = factorResolver.toSnapshot(plan, useDefaultFactors);
        com.ruoyi.carbon.report.source.ReportMonthlyActivityBuilder.Series monthly =
                com.ruoyi.carbon.report.source.ReportMonthlyActivityBuilder.load(calculationMapper, draft.getTask());
        String snapshot = assembler.assemble(draft, profileMapper.selectByDeptId(deptId), factors,
                monthly.fuels(), monthly.electricity());
        String hash = SnapshotHasher.sha256(snapshot);
        String kind = outputKind == null ? "docx" : outputKind;
        ReportFile existing = fileMapper.selectByDeptSnapshotRole(deptId, hash, kindRole(kind));
        if (reusable(existing) && !aiEnabled)
        {
            return cachedJob(reportId, deptId, kind, hash, snapshot, existing);
        }
        ReportGenerationJob job = new ReportGenerationJob();
        job.setDeptId(deptId);
        job.setReportId(reportId);
        job.setOutputKind(kind);
        job.setStatus("queued");
        job.setProgress(0);
        job.setSnapshotSha256(hash);
        job.setInputSnapshotJson(snapshot);
        job.setAiEnabled(aiEnabled ? "1" : "0");
        job.setLlmCallCount(0);
        jobMapper.insert(job);
        executor.execute(() -> run(job, snapshot, aiEnabled, llmConfig));
        return job;
    }

    @Override
    public void testLlmConnection(LlmRuntimeConfig llmConfig)
    {
        reportRenderer.testLlmConnection(llmConfig);
    }

    @Override
    public ReportGenerationJob latest(Long reportId, Long deptId)
    {
        reportTaskService.get(reportId, deptId);
        ReportGenerationJob job = jobMapper.selectLatestSucceeded(reportId, deptId);
        if (job == null)
        {
            return null;
        }
        if (job.getDocxFileId() == null)
        {
            job.setDocxFileId(jobMapper.selectLatestDocxFileId(reportId, deptId));
        }
        if (job.getPdfFileId() == null)
        {
            job.setPdfFileId(jobMapper.selectLatestPdfFileId(reportId, deptId));
        }
        return job;
    }

    @Override
    public ReportGenerationJob get(Long reportId, Long jobId, Long deptId)
    {
        reportTaskService.get(reportId, deptId);
        ReportGenerationJob job = jobMapper.selectById(jobId);
        if (job == null || !deptId.equals(job.getDeptId()) || !reportId.equals(job.getReportId()))
        {
            ReportAccessGuard.requireTask(null, deptId);
        }
        return job;
    }

    @Override
    public ReportFile downloadMeta(Long artifactId, Long deptId)
    {
        return artifacts.requireDept(fileMapper.selectById(artifactId), deptId);
    }

    @Override
    public InputStream downloadStream(Long artifactId, Long deptId)
    {
        ReportFile meta = downloadMeta(artifactId, deptId);
        byte[] bytes = ReportFileBytes.read(meta, artifacts, fileMapper);
        if (bytes == null || bytes.length == 0)
        {
            throw new ServiceException("not found", HttpStatus.NOT_FOUND);
        }
        return new ByteArrayInputStream(bytes);
    }

    private void run(ReportGenerationJob job, String snapshot, boolean aiEnabled, LlmRuntimeConfig llmConfig)
    {
        try
        {
            job.setStatus("processing");
            job.setProgress(10);
            jobMapper.update(job);
            ReportFile docx = aiEnabled ? null
                    : fileMapper.selectByDeptSnapshotRole(job.getDeptId(), job.getSnapshotSha256(), "docx");
            Path workRoot = properties.workDirPath().resolve("job-" + job.getId());
            Files.createDirectories(workRoot);
            Path producedDocx = materializeCached(docx, workRoot.resolve("cached.docx"));
            if (producedDocx == null)
            {
                docx = null;
            }
            RenderPlan plan = RenderPlan.of(job.getOutputKind(), docx != null, aiEnabled);
            job.setProgress(plan.callLlm ? 40 : 70);
            jobMapper.update(job);
            if (plan.generateDocx)
            {
                Path tempDocx = workRoot.resolve("report.docx");
                RenderResult result = reportRenderer.generateDocx(snapshot, plan.callLlm, tempDocx, llmConfig);
                docx = insertFile(job, result.getOutputPath(), "docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
                producedDocx = result.getOutputPath();
                job.setDocxFileId(docx.getId());
                job.setLlmCallCount(plan.callLlm ? (result.isLlmUsed() ? 1 : -1) : 0);
            }
            else if (docx != null)
            {
                job.setDocxFileId(docx.getId());
                job.setLlmCallCount(0);
            }
            if (plan.convertPdf)
            {
                job.setProgress(90);
                jobMapper.update(job);
                Path tempPdf = workRoot.resolve("report.pdf");
                reportRenderer.convertPdf(producedDocx, tempPdf);
                ReportFile pdf = insertFile(job, tempPdf, "pdf", "application/pdf");
                job.setPdfFileId(pdf.getId());
            }
            job.setProgress(100);
            job.setStatus("succeeded");
            jobMapper.update(job);
            reportTaskService.markGenerated(job.getReportId(), job.getDeptId());
            deleteTree(workRoot);
        }
        catch (Exception ex)
        {
            job.setStatus("failed");
            job.setErrorMessage(ex.getMessage());
            jobMapper.update(job);
        }
    }

    private ReportGenerationJob cachedJob(Long reportId, Long deptId, String kind, String hash,
            String snapshot, ReportFile existing)
    {
        ReportGenerationJob job = new ReportGenerationJob();
        job.setDeptId(deptId);
        job.setReportId(reportId);
        job.setOutputKind(kind);
        job.setStatus("succeeded");
        job.setProgress(100);
        job.setSnapshotSha256(hash);
        job.setInputSnapshotJson(snapshot);
        job.setLlmCallCount(0);
        if ("pdf".equalsIgnoreCase(kind))
        {
            job.setPdfFileId(existing.getId());
            ReportFile docx = fileMapper.selectByDeptSnapshotRole(deptId, hash, "docx");
            if (docx != null)
            {
                job.setDocxFileId(docx.getId());
            }
        }
        else
        {
            job.setDocxFileId(existing.getId());
        }
        jobMapper.insert(job);
        reportTaskService.markGenerated(reportId, deptId);
        return job;
    }

    private ReportFile insertFile(ReportGenerationJob job, Path stored, String role, String mime) throws Exception
    {
        byte[] bytes = Files.readAllBytes(stored);
        ReportFile file = new ReportFile();
        file.setDeptId(job.getDeptId());
        file.setReportId(job.getReportId());
        file.setKind("generated");
        file.setRole(role);
        file.setObjectKey("");
        file.setContent(bytes);
        com.alibaba.fastjson2.JSONObject input = com.alibaba.fastjson2.JSON.parseObject(job.getInputSnapshotJson());
        file.setOriginalName(input != null && input.getIntValue("period_contract_version") == 1
                ? com.ruoyi.carbon.report.source.ReportPeriodSnapshot.fileName(
                        input.getJSONObject("metadata").getString("report_title"), role)
                : stored.getFileName().toString());
        file.setMimeType(mime);
        file.setSizeBytes((long) bytes.length);
        file.setSha256(SnapshotHasher.sha256(bytes));
        file.setSnapshotSha256(job.getSnapshotSha256());
        fileMapper.insert(file);
        file.setContent(null);
        return file;
    }

    private boolean reusable(ReportFile file)
    {
        if (file == null)
        {
            return false;
        }
        if (file.getSha256() != null && !file.getSha256().isBlank()
                && file.getSizeBytes() != null && file.getSizeBytes() > 0)
        {
            return true;
        }
        if (file.getObjectKey() == null || file.getObjectKey().isBlank())
        {
            return false;
        }
        try
        {
            return Files.isRegularFile(artifacts.resolve(file));
        }
        catch (RuntimeException ex)
        {
            return false;
        }
    }

    private Path materializeCached(ReportFile file, Path dest) throws Exception
    {
        if (!reusable(file))
        {
            return null;
        }
        byte[] bytes = ReportFileBytes.read(file, artifacts, fileMapper);
        if (bytes == null || bytes.length == 0)
        {
            return null;
        }
        Files.createDirectories(dest.getParent());
        Files.write(dest, bytes);
        return dest;
    }

    private static void deleteTree(Path root)
    {
        if (root == null || !Files.exists(root))
        {
            return;
        }
        try (java.util.stream.Stream<Path> walk = Files.walk(root))
        {
            walk.sorted(Comparator.reverseOrder()).forEach(path -> {
                try
                {
                    Files.deleteIfExists(path);
                }
                catch (Exception ignored)
                {
                }
            });
        }
        catch (Exception ignored)
        {
        }
    }

    private static String kindRole(String kind)
    {
        return "pdf".equalsIgnoreCase(kind) ? "pdf" : "docx";
    }

    private static String missingMessage(ReportFactorPlan plan)
    {
        String reason = plan.getReason() == null || plan.getReason().isBlank() ? "现用核算模板缺少因子" : plan.getReason();
        if (plan.getMissing() == null || plan.getMissing().isEmpty())
        {
            return reason;
        }
        return reason + "：" + String.join("、", plan.getMissing()) + "。请确认是否使用系统默认因子。";
    }
}
