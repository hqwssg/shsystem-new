package com.ruoyi.carbon.report.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.ReportGenerationJob;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.generation.CarbonReportRendererProperties;
import com.ruoyi.carbon.report.generation.DiskArtifactStore;
import com.ruoyi.carbon.report.generation.RenderResult;
import com.ruoyi.carbon.report.generation.ReportRenderer;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptProfileMapper;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;
import com.ruoyi.carbon.report.mapper.ReportGenerationJobMapper;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

class ReportGenerationServiceImplTest
{
    @TempDir
    Path temp;

    @Test
    void aiGenerationUsesRequestConfigAndBypassesExistingArtifact() throws Exception
    {
        var config = new com.ruoyi.carbon.report.generation.LlmRuntimeConfig("https://example.com", "model-a", "test-key");
        ReportFileMapper files = mock(ReportFileMapper.class);
        ReportFile old = new ReportFile(); old.setId(9L); old.setDeptId(301L);
        old.setRole("docx"); old.setContent(new byte[] {'P','K',3,4});
        when(files.selectByDeptSnapshotRole(eq(301L), anyString(), eq("docx"))).thenReturn(old);
        when(files.insert(any(ReportFile.class))).thenAnswer(i -> { ((ReportFile)i.getArgument(0)).setId(21L); return 1; });
        ReportRenderer renderer = new ReportRenderer() {
            @Override public RenderResult generateDocx(String snapshot, boolean ai, Path output) {
                throw new AssertionError("request configuration must be forwarded");
            }
            @Override public RenderResult generateDocx(String snapshot, boolean ai, Path output,
                    com.ruoyi.carbon.report.generation.LlmRuntimeConfig actual) {
                assertTrue(ai); assertEquals(config, actual); assertTrue(!snapshot.contains("test-key"));
                try { Files.createDirectories(output.getParent()); Files.write(output, new byte[] {'P','K',3,4}); }
                catch (Exception ex) { throw new RuntimeException(ex); }
                return new RenderResult(output, true);
            }
            @Override public RenderResult convertPdf(Path docx, Path output) { throw new AssertionError(); }
        };
        ReportGenerationJob job = service(renderer, files).create(1L, 301L, "docx", true, true, config);
        assertEquals("succeeded", job.getStatus(), job.getErrorMessage());
        assertEquals(21L, job.getDocxFileId()); assertEquals(1, job.getLlmCallCount());
        assertTrue(!job.getInputSnapshotJson().contains("test-key"));
    }

    @Test
    void missingWorkloadAllowsDocxAndPdfWithoutAddingZeroRows() throws Exception
    {
        ReportDraft draft = draft();
        draft.setWorkloadCount(0);
        AtomicInteger renders = new AtomicInteger();
        ReportRenderer renderer = new ReportRenderer() {
            @Override public RenderResult generateDocx(String snapshot, boolean aiEnabled, Path output) {
                assertTrue(com.alibaba.fastjson2.JSON.parseObject(snapshot).getJSONArray("workload").isEmpty());
                assertTrue(draft.getWorkload().isEmpty());
                renders.incrementAndGet();
                try { Files.createDirectories(output.getParent());Files.write(output, new byte[] {'P','K',3,4}); }
                catch (Exception ex) { throw new RuntimeException(ex); }
                return new RenderResult(output, false);
            }
            @Override public RenderResult convertPdf(Path docx, Path output) {
                try { Files.writeString(output, "%PDF-1.4\n"); }
                catch (Exception ex) { throw new RuntimeException(ex); }
                return new RenderResult(output, false);
            }
        };
        ReportFileMapper files = mock(ReportFileMapper.class);
        when(files.insert(any(ReportFile.class))).thenAnswer(invocation -> {
            ReportFile file = invocation.getArgument(0);file.setId(21L);return 1;
        });
        ReportGenerationServiceImpl service = service(renderer, files, draft);
        for (String kind : java.util.List.of("docx", "pdf")) {
            ReportGenerationJob job = service.create(1L, 301L, kind, false, true);
            assertEquals("succeeded", job.getStatus(), job.getErrorMessage());
            assertEquals(21L, job.getDocxFileId());
            if ("pdf".equals(kind)) assertEquals(21L, job.getPdfFileId());
        }
        assertEquals(2, renders.get());
    }

    @Test
    void changedNewPeriodSourceIsRejectedBeforeEnqueuingOrRendering() {
        IReportTaskService tasks = mock(IReportTaskService.class);
        ReportDraft draft = draft();
        com.ruoyi.carbon.report.domain.CalculationCandidate candidate = new com.ruoyi.carbon.report.domain.CalculationCandidate();
        candidate.setId(11L);candidate.setTemplateId(503L);candidate.setStatus(2);candidate.setCompanyDeptId(301L);candidate.setTemplateName("测试模板");
        candidate.setCycleStart(java.sql.Date.valueOf("2025-03-01"));candidate.setCycleEnd(java.sql.Date.valueOf("2025-05-31"));
        com.ruoyi.carbon.report.domain.dto.CreateReportRequest request = new com.ruoyi.carbon.report.domain.dto.CreateReportRequest();
        request.setPeriodMode("CALCULATION");request.setCalculationTemplateId(11L);
        com.ruoyi.carbon.report.source.ReportPeriodSnapshot.initialize(draft.getTask(), request, candidate, "测试公司");
        draft.getTask().setCalculationTemplateId(11L);
        com.ruoyi.carbon.report.domain.dto.PrefillResult source = new com.ruoyi.carbon.report.domain.dto.PrefillResult();
        source.setSourceSignature("stale-evidence");com.ruoyi.carbon.report.source.ReportPeriodSnapshot.freezeSource(draft.getTask(), source);
        when(tasks.getDraft(1L,301L)).thenReturn(draft);
        EmissionCalculationMapper calculations=mock(EmissionCalculationMapper.class);
        when(calculations.selectTask(11L)).thenReturn(candidate);
        when(calculations.selectCompanyCandidates(eq(301L),any(),any())).thenReturn(java.util.List.of(candidate));
        when(calculations.selectNodeData(11L)).thenReturn(java.util.List.of());
        ReportGenerationJobMapper jobs=mock(ReportGenerationJobMapper.class);
        ReportGenerationServiceImpl service=new ReportGenerationServiceImpl(tasks,mock(ReportDeptProfileMapper.class),jobs,
                mock(ReportFileMapper.class),mock(ReportRenderer.class),properties(),calculations,Runnable::run);
        ServiceException ex=assertThrows(ServiceException.class,()->service.create(1L,301L,"docx",false,false));
        assertEquals(409,ex.getCode());assertTrue(ex.getMessage().contains("来源已变化"));
        verify(jobs,never()).insert(any());
    }

    @Test
    void createRejectsUnfrozenCalculationSourceBeforeRendering()
    {
        IReportTaskService tasks = mock(IReportTaskService.class);
        ReportDraft draft = draft();
        ReportActivityRow fuel = new ReportActivityRow();
        fuel.setFuelType("diesel");
        fuel.setNormalizedValue(new java.math.BigDecimal("10"));
        draft.getFuels().add(fuel);
        draft.getTask().setCalculationTemplateId(11L);
        when(tasks.getDraft(1L, 301L)).thenReturn(draft);
        EmissionCalculationMapper calcMapper = mock(EmissionCalculationMapper.class);
        when(calcMapper.selectFactorTemplateLink(11L)).thenReturn(null);
        ReportGenerationServiceImpl service = new ReportGenerationServiceImpl(
                tasks, mock(ReportDeptProfileMapper.class), mock(ReportGenerationJobMapper.class),
                mock(ReportFileMapper.class), mock(ReportRenderer.class), properties(), calcMapper, Runnable::run);
        ServiceException ex = assertThrows(ServiceException.class, () -> service.create(1L, 301L, "docx", false, false));
        assertEquals(HttpStatus.BAD_REQUEST, ex.getCode());
        assertTrue(ex.getMessage().contains("冻结核算来源"));
    }

    @Test
    void pdfWithExistingDocxDoesNotCallGenerateDocx() throws Exception
    {
        AtomicInteger generateCalls = new AtomicInteger();
        AtomicInteger convertCalls = new AtomicInteger();
        ReportRenderer renderer = new ReportRenderer()
        {
            @Override
            public RenderResult generateDocx(String snapshotJson, boolean aiEnabled, Path outputPath)
            {
                generateCalls.incrementAndGet();
                throw new AssertionError("must reuse existing DOCX");
            }

            @Override
            public RenderResult convertPdf(Path docxPath, Path outputPath)
            {
                convertCalls.incrementAndGet();
                try
                {
                    Files.createDirectories(outputPath.getParent());
                    Files.write(outputPath, "%PDF-1.4\n".getBytes());
                }
                catch (Exception ex)
                {
                    throw new RuntimeException(ex);
                }
                return new RenderResult(outputPath, false);
            }
        };
        ReportFileMapper fileMapper = mock(ReportFileMapper.class);
        when(fileMapper.selectByDeptSnapshotRole(eq(301L), anyString(), eq("pdf"))).thenReturn(null);
        when(fileMapper.selectByDeptSnapshotRole(eq(301L), anyString(), eq("docx"))).thenAnswer(invocation -> {
            String hash = invocation.getArgument(1);
            DiskArtifactStore store = new DiskArtifactStore(properties().artifactDirPath());
            Path path = store.prepare(301L, hash, "docx", "docx");
            Files.write(path, new byte[] { 'P', 'K', 3, 4 });
            ReportFile existing = new ReportFile();
            existing.setId(9L);
            existing.setDeptId(301L);
            existing.setRole("docx");
            existing.setObjectKey(store.relativeKey(path));
            return existing;
        });
        when(fileMapper.insert(any(ReportFile.class))).thenAnswer(invocation -> {
            ReportFile file = invocation.getArgument(0);
            file.setId(21L);
            return 1;
        });

        ReportGenerationServiceImpl service = service(renderer, fileMapper);
        ReportGenerationJob job = service.create(1L, 301L, "pdf", false, true);
        assertEquals("succeeded", job.getStatus());
        assertEquals(0, generateCalls.get());
        assertEquals(1, convertCalls.get());
        assertEquals(9L, job.getDocxFileId());
        assertEquals(21L, job.getPdfFileId());
        verify(fileMapper).insert(any(ReportFile.class));
    }

    @Test
    void pdfFailureKeepsExistingDocxRow()
    {
        ReportRenderer renderer = new ReportRenderer()
        {
            @Override
            public RenderResult generateDocx(String snapshotJson, boolean aiEnabled, Path outputPath)
            {
                throw new AssertionError("must not regenerate Word after a DOCX cache hit");
            }

            @Override
            public RenderResult convertPdf(Path docxPath, Path outputPath)
            {
                throw new ServiceException("LibreOffice missing");
            }
        };
        ReportFileMapper fileMapper = mock(ReportFileMapper.class);
        when(fileMapper.selectByDeptSnapshotRole(eq(301L), anyString(), eq("pdf"))).thenReturn(null);
        when(fileMapper.selectByDeptSnapshotRole(eq(301L), anyString(), eq("docx"))).thenAnswer(invocation -> {
            String hash = invocation.getArgument(1);
            DiskArtifactStore store = new DiskArtifactStore(properties().artifactDirPath());
            Path path = store.prepare(301L, hash, "docx", "docx");
            Files.write(path, new byte[] { 'P', 'K' });
            ReportFile existing = new ReportFile();
            existing.setId(9L);
            existing.setDeptId(301L);
            existing.setObjectKey(store.relativeKey(path));
            return existing;
        });

        ReportGenerationJob job = service(renderer, fileMapper).create(1L, 301L, "pdf", false, true);
        assertEquals("failed", job.getStatus());
        assertEquals(9L, job.getDocxFileId());
        verify(fileMapper, never()).insert(any(ReportFile.class));
    }

    @Test
    void downloadRejectsOtherDeptAndSurvivesStoreRestart() throws Exception
    {
        DiskArtifactStore store = new DiskArtifactStore(properties().artifactDirPath());
        Path path = store.prepare(301L, "sha", "docx", "docx");
        Files.write(path, new byte[] { 'P', 'K', 3, 4 });
        ReportFile meta = new ReportFile();
        meta.setId(8L);
        meta.setDeptId(301L);
        meta.setObjectKey(store.relativeKey(path));
        meta.setMimeType("application/octet-stream");
        meta.setOriginalName("docx.docx");

        ReportFileMapper fileMapper = mock(ReportFileMapper.class);
        when(fileMapper.selectById(8L)).thenReturn(meta);
        ReportGenerationServiceImpl first = service(mock(ReportRenderer.class), fileMapper);
        ServiceException hidden = assertThrows(ServiceException.class, () -> first.downloadMeta(8L, 302L));
        assertEquals(HttpStatus.NOT_FOUND, hidden.getCode());

        ReportGenerationServiceImpl restarted = service(mock(ReportRenderer.class), fileMapper);
        try (InputStream in = restarted.downloadStream(8L, 301L))
        {
            assertEquals('P', in.read());
            assertEquals('K', in.read());
        }
        assertTrue(Files.isRegularFile(store.resolve(meta)));
    }

    @Test
    void latestMergesDocxAndPdfFromSucceededJobs()
    {
        IReportTaskService tasks = mock(IReportTaskService.class);
        when(tasks.get(1L, 301L)).thenReturn(draft().getTask());
        ReportGenerationJob latest = new ReportGenerationJob();
        latest.setId(4L);
        latest.setDeptId(301L);
        latest.setReportId(1L);
        latest.setStatus("succeeded");
        latest.setPdfFileId(22L);
        ReportGenerationJobMapper jobs = mock(ReportGenerationJobMapper.class);
        when(jobs.selectLatestSucceeded(1L, 301L)).thenReturn(latest);
        when(jobs.selectLatestDocxFileId(1L, 301L)).thenReturn(21L);
        ReportGenerationServiceImpl svc = new ReportGenerationServiceImpl(
                tasks, mock(ReportDeptProfileMapper.class), jobs, mock(ReportFileMapper.class),
                mock(ReportRenderer.class), properties(), mock(EmissionCalculationMapper.class), Runnable::run);
        ReportGenerationJob job = svc.latest(1L, 301L);
        assertEquals(21L, job.getDocxFileId());
        assertEquals(22L, job.getPdfFileId());
    }

    private ReportGenerationServiceImpl service(ReportRenderer renderer, ReportFileMapper fileMapper)
    {
        return service(renderer, fileMapper, draft());
    }

    private ReportGenerationServiceImpl service(ReportRenderer renderer, ReportFileMapper fileMapper, ReportDraft draft)
    {
        IReportTaskService tasks = mock(IReportTaskService.class);
        when(tasks.getDraft(1L, 301L)).thenReturn(draft);
        ReportDeptProfileMapper profiles = mock(ReportDeptProfileMapper.class);
        ReportGenerationJobMapper jobs = mock(ReportGenerationJobMapper.class);
        when(jobs.insert(any(ReportGenerationJob.class))).thenAnswer(invocation -> {
            ReportGenerationJob job = invocation.getArgument(0);
            if (job.getId() == null)
            {
                job.setId(1L);
            }
            return 1;
        });
        when(jobs.update(any(ReportGenerationJob.class))).thenReturn(1);
        return new ReportGenerationServiceImpl(tasks, profiles, jobs, fileMapper, renderer, properties(),
                mock(EmissionCalculationMapper.class), Runnable::run);
    }

    private CarbonReportRendererProperties properties()
    {
        CarbonReportRendererProperties properties = new CarbonReportRendererProperties();
        properties.setPythonExecutable("python");
        properties.setModuleRoot(temp.toString());
        properties.setWorkDir(temp.resolve("work").toString());
        properties.setArtifactDir(temp.resolve("artifacts").toString());
        properties.setTimeoutSeconds(30);
        properties.setMaxLogBytes(1024);
        return properties;
    }

    private static ReportDraft draft()
    {
        ReportTask task = new ReportTask();
        task.setId(1L);
        task.setDeptId(301L);
        task.setTitle("测试报告");
        task.setReportYear(2024);
        task.setPeriodType("YEAR");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.setWorkloadCount(1);
        ReportActivityRow electricity = new ReportActivityRow();
        electricity.setNormalizedValue(java.math.BigDecimal.ONE);
        draft.getElectricity().add(electricity);
        return draft;
    }
}
