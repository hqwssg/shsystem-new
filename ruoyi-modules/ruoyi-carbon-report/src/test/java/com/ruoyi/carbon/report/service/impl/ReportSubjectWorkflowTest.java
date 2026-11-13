package com.ruoyi.carbon.report.service.impl;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.util.Date;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import com.alibaba.fastjson2.JSON;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.CreateReportRequest;
import com.ruoyi.carbon.report.mapper.*;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.carbon.report.source.ReportSubjectSnapshot;
import com.ruoyi.carbon.report.source.ReportCalculationSelection;
import com.ruoyi.common.core.exception.ServiceException;

class ReportSubjectWorkflowTest
{
    private static ReportDeptSubject subject(Long node, String allocation)
    {
        ReportDeptSubject s = new ReportDeptSubject(); s.setSubjectNodeId(node); s.setEnergyAllocation(allocation); return s;
    }

    @Test void MappingChangesDoNotRebindNewReportsAndBasicSaveCannotForgeSnapshot()
    {
        ReportTask task = new ReportTask(); task.setDeptId(303L);
        ReportSubjectSnapshot.freeze(task, subject(3171L, "jilong"));
        task.setMetadataJson(ReportSubjectSnapshot.preserveOnBasicSave(task.getMetadataJson(),
                "{\"compiler\":\"admin\",\"_report_subject\":{\"energyAllocation\":\"suring\"}}"));
        ReportDeptSubject frozen = ReportSubjectSnapshot.resolve(task, subject(3L, "suring"));
        assertEquals(3171L, frozen.getSubjectNodeId()); assertEquals("jilong", frozen.getEnergyAllocation());
        assertEquals("admin", JSON.parseObject(task.getMetadataJson()).getString("compiler"));
        assertEquals("jilong", ReportSubjectSnapshot.resolve(task, null).getEnergyAllocation());
    }

    @Test void LegacyReportStillReadsButCannotImportFromChangedMapping()
    {
        ReportTask task = new ReportTask(); task.setSubjectNodeId(3171L);
        assertEquals("jilong", ReportSubjectSnapshot.resolve(task, subject(3171L, "jilong")).getEnergyAllocation());
        assertThrows(ServiceException.class, () -> ReportSubjectSnapshot.resolve(task, subject(3L, "suring")));
        assertFalse(JSON.parseObject(ReportSubjectSnapshot.preserveOnBasicSave(null,
                "{\"_report_subject\":{\"energyAllocation\":\"suring\"}}")).containsKey(ReportSubjectSnapshot.KEY));
    }

    @Test void SelectionRejectsFailedWrongSubjectAndWrongPeriodBeforeReadingDetails()
    {
        EmissionCalculationMapper mapper = mock(EmissionCalculationMapper.class);
        Date start = new Date(1000), end = new Date(2000);
        CalculationCandidate failed = new CalculationCandidate(); failed.setId(4172L); failed.setStatus(3);
        when(mapper.selectCandidates(3171L, start, end)).thenReturn(List.of(failed));
        assertThrows(ServiceException.class, () -> ReportCalculationSelection.require(mapper, 3171L, 4172L, start, end));
        failed.setStatus(2);
        ReportCalculationSelection.require(mapper, 3171L, 4172L, start, end);
        assertThrows(ServiceException.class, () -> ReportCalculationSelection.require(mapper, 3L, 4172L, start, end));
        assertThrows(ServiceException.class, () -> ReportCalculationSelection.require(mapper, 3171L, 4172L, end, start));
        verify(mapper, never()).selectNodeData(anyLong());
    }

    @Test void CreationRejectsForeignTaskBeforeInsertAndFreezesValidSelection()
    {
        ReportTaskMapper tasks = mock(ReportTaskMapper.class);
        ReportDeptSubjectMapper subjects = mock(ReportDeptSubjectMapper.class);
        EmissionCalculationMapper calculations = mock(EmissionCalculationMapper.class);
        ReportTaskServiceImpl service = new ReportTaskServiceImpl();
        ReflectionTestUtils.setField(service, "reportTaskMapper", tasks);
        ReflectionTestUtils.setField(service, "reportDeptSubjectMapper", subjects);
        ReflectionTestUtils.setField(service, "emissionCalculationMapper", calculations);
        when(subjects.selectByDeptId(303L)).thenReturn(subject(3171L, "jilong"));
        CreateReportRequest request = new CreateReportRequest(); request.setReportYear(2025); request.setPeriodType("YEAR"); request.setCalculationTemplateId(4172L);
        when(calculations.selectCandidates(eq(3171L), any(), any())).thenReturn(List.of());
        assertThrows(ServiceException.class, () -> service.create(request, 303L, "admin"));
        verify(tasks, never()).insert(any());
        CalculationCandidate valid = new CalculationCandidate(); valid.setId(4172L); valid.setStatus(2);
        when(calculations.selectCandidates(eq(3171L), any(), any())).thenReturn(List.of(valid));
        ReportTask task = service.create(request, 303L, "admin");
        assertEquals(303L, task.getDeptId()); assertEquals(3171L, task.getSubjectNodeId());
        assertEquals("admin", task.getCreateBy());
        assertEquals("jilong", ReportSubjectSnapshot.resolve(task, subject(3L, "suring")).getEnergyAllocation());
        verify(tasks).insert(task);
    }

    @Test void PreviewAndCommitRejectForeignTaskWithoutDeletingExistingActivities()
    {
        IReportTaskService tasks = mock(IReportTaskService.class);
        ReportTask task = new ReportTask(); task.setDeptId(303L); task.setPeriodStart(new Date(1000)); task.setPeriodEnd(new Date(2000));
        ReportSubjectSnapshot.freeze(task, subject(3171L, "jilong"));
        when(tasks.get(1L, 303L)).thenReturn(task);
        EmissionCalculationMapper calculations = mock(EmissionCalculationMapper.class);
        ReportActivityMapper activities = mock(ReportActivityMapper.class);
        ReportSourceServiceImpl service = new ReportSourceServiceImpl();
        ReflectionTestUtils.setField(service, "reportTaskService", tasks);
        ReflectionTestUtils.setField(service, "subjectMapper", mock(ReportDeptSubjectMapper.class));
        ReflectionTestUtils.setField(service, "calculationMapper", calculations);
        ReflectionTestUtils.setField(service, "activityMapper", activities);
        assertThrows(ServiceException.class, () -> service.commit(1L, 303L, 999L));
        verifyNoInteractions(activities);
        verify(calculations, never()).selectNodeData(anyLong());
    }

    @Test void BlankOrIncompleteMappingCannotCreateReport()
    {
        assertThrows(ServiceException.class, () -> ReportSubjectSnapshot.freeze(new ReportTask(), null));
        assertThrows(ServiceException.class, () -> ReportSubjectSnapshot.freeze(new ReportTask(), subject(3171L, "")));
    }
}
