package com.ruoyi.carbon.report.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.CreateReportRequest;
import com.ruoyi.carbon.report.mapper.*;
import com.ruoyi.carbon.report.source.*;
import com.ruoyi.carbon.report.service.impl.*;
import com.ruoyi.common.core.exception.ServiceException;

class ReportCompanySelectionTest {
    private CalculationCandidate candidate(long id, Long company) {
        CalculationCandidate row = new CalculationCandidate(); row.setId(id); row.setCompanyDeptId(company); row.setStatus(2); return row;
    }
    private ReportDeptSubject subject() {
        ReportDeptSubject subject = new ReportDeptSubject(); subject.setDeptId(302L); subject.setEnergyAllocation("yuanping"); return subject;
    }

    @Test void CompanySnapshotSelectsIndependentYearlyNodesWithoutRequiringOneFixedNode() {
        EmissionCalculationMapper mapper = mock(EmissionCalculationMapper.class);
        when(mapper.selectCompanyCandidates(eq(302L), any(), any())).thenReturn(List.of(candidate(1,302L),candidate(2,302L),candidate(3,303L)));
        ReportTask task = new ReportTask(); task.setDeptId(302L); ReportSubjectSnapshot.freezeCompany(task,subject());
        assertEquals(List.of(1L,2L), ReportCalculationSelection.forReport(mapper,task,subject(),new Date(0),new Date(1)).stream().map(CalculationCandidate::getId).toList());
        verify(mapper,never()).selectCandidates(any(),any(),any());
        assertThrows(ServiceException.class, () -> ReportCalculationSelection.requireForReport(mapper,task,subject(),3L,new Date(0),new Date(1)));
    }

    @Test void LegacyNodeCannotOverrideAConfirmedDifferentCompany() {
        EmissionCalculationMapper mapper=mock(EmissionCalculationMapper.class);
        when(mapper.selectCompanyCandidates(eq(302L),any(),any())).thenReturn(List.of(candidate(1,302L)));
        when(mapper.selectCandidates(eq(1001L),any(),any())).thenReturn(List.of(candidate(2,null),candidate(3,303L),candidate(1,302L)));
        assertEquals(List.of(1L,2L), ReportCalculationSelection.companyCandidates(mapper,302L,1001L,new Date(0),new Date(1)).stream().map(CalculationCandidate::getId).toList());
    }

    @Test void CompanyReportFreezesAllocationAndKeepsModeOnBasicEdits() {
        ReportTask task=new ReportTask();task.setDeptId(302L); ReportSubjectSnapshot.freezeCompany(task,subject());
        ReportDeptSubject changed=subject();changed.setEnergyAllocation("jilong");changed.setSubjectNodeId(999L);
        assertNull(ReportSubjectSnapshot.resolve(task,changed).getSubjectNodeId());
        assertEquals("yuanping",ReportSubjectSnapshot.resolve(task,changed).getEnergyAllocation());
        task.setMetadataJson(ReportSubjectSnapshot.preserveOnBasicSave(task.getMetadataJson(),"{\"_report_subject\":{\"mode\":\"NODE\"}}"));
        assertTrue(ReportSubjectSnapshot.isCompany(task));
    }

    @Test void CreateValidatesCompanyBeforeInsertingAndWorksWithoutNodeMapping() {
        ReportTaskServiceImpl service=new ReportTaskServiceImpl();
        ReportTaskMapper tasks=mock(ReportTaskMapper.class);ReportDeptSubjectMapper subjects=mock(ReportDeptSubjectMapper.class);
        EmissionCalculationMapper mapper=mock(EmissionCalculationMapper.class);
        ReflectionTestUtils.setField(service,"reportTaskMapper",tasks);ReflectionTestUtils.setField(service,"reportDeptSubjectMapper",subjects);
        ReflectionTestUtils.setField(service,"emissionCalculationMapper",mapper);
        when(subjects.selectByDeptId(302L)).thenReturn(subject());
        CreateReportRequest request=new CreateReportRequest();request.setReportYear(2025);request.setCalculationTemplateId(1L);
        assertThrows(ServiceException.class,()->service.create(request,302L,"admin"));verify(tasks,never()).insert(any());
        when(mapper.selectCompanyCandidates(eq(302L),any(),any())).thenReturn(List.of(candidate(1,302L)));
        ReportTask task=service.create(request,302L,"admin");assertNull(task.getSubjectNodeId());assertTrue(ReportSubjectSnapshot.isCompany(task));verify(tasks).insert(task);
    }

    @Test void UnconfiguredAllocationStillRejectsAndCompanyReadinessNoLongerRequiresNode() {
        assertThrows(ServiceException.class,()->ReportSubjectSnapshot.freezeCompany(new ReportTask(),new ReportDeptSubject()));
        ReportSubjectOption option=new ReportSubjectOption();option.setEnergyAllocation("yuanping");assertTrue(option.isConfigured());
    }

    @Test void NewManualCreationAndIdempotentRetryDoNotCreateDuplicateDrafts() {
        ReportTaskServiceImpl service=new ReportTaskServiceImpl();
        ReportTaskMapper tasks=mock(ReportTaskMapper.class);ReportDeptSubjectMapper subjects=mock(ReportDeptSubjectMapper.class);
        ReflectionTestUtils.setField(service,"reportTaskMapper",tasks);ReflectionTestUtils.setField(service,"reportDeptSubjectMapper",subjects);
        when(subjects.selectByDeptId(302L)).thenReturn(subject());
        ReportSubjectOption company=new ReportSubjectOption();company.setDeptId(302L);company.setDeptName("原平分公司");
        when(subjects.selectCompanies(any())).thenReturn(List.of(company));
        CreateReportRequest request=new CreateReportRequest();request.setPeriodMode("MANUAL");request.setPeriodStart("2024-01-01");request.setPeriodEnd("2025-05-31");
        request.setRequestKey("report-unique-creation-key");
        ReportTask created=service.create(request,302L,"admin");assertEquals("RANGE",created.getPeriodType());
        assertTrue(created.getMetadataJson().contains("_report_request_key"));
        when(tasks.selectCreationRequest(302L,"admin",request.getRequestKey())).thenReturn(created);
        assertSame(created,service.create(request,302L,"admin"));verify(tasks,times(1)).insert(any());
        request.setPeriodEnd("2025-06-30");assertThrows(ServiceException.class,()->service.create(request,302L,"admin"));
    }
}
