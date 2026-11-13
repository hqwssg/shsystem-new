package com.ruoyi.carbon.report.service.impl;

import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.PrefillLine;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.mapper.ReportActivityMapper;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.common.core.exception.ServiceException;

class ReportReviewedPrefillTest {
    private ReportSourceServiceImpl service(PrefillResult preview, ReportActivityMapper activities) {
        ReportSourceServiceImpl service=spy(new ReportSourceServiceImpl());
        ReportTask task=new ReportTask();task.setId(1L);task.setDeptId(2L);task.setVersion(3);task.setCalculationTemplateId(8L);
        IReportTaskService tasks=mock(IReportTaskService.class);when(tasks.get(1L,2L)).thenReturn(task);
        ReflectionTestUtils.setField(service,"reportTaskService",tasks);ReflectionTestUtils.setField(service,"activityMapper",activities);
        doReturn(preview).when(service).preview(1L,2L,8L);return service;
    }
    @Test void staleVersionOrHashDoesNotDeleteExistingRows() {
        PrefillResult result=new PrefillResult();result.setPreviewHash("fresh");result.getFuels().add(new PrefillLine());
        ReportActivityMapper activities=mock(ReportActivityMapper.class);var svc=service(result,activities);
        assertThrows(ServiceException.class,()->svc.commitReviewed(1L,2L,8L,2,"fresh",true));
        assertThrows(ServiceException.class,()->svc.commitReviewed(1L,2L,8L,3,"stale",true));
        verifyNoInteractions(activities);
    }
    @Test void emptyResultOrUnconfirmedPartialDoesNotDeleteExistingRows() {
        PrefillResult result=new PrefillResult();result.setPreviewHash("fresh");
        ReportActivityMapper activities=mock(ReportActivityMapper.class);var svc=service(result,activities);
        assertThrows(ServiceException.class,()->svc.commitReviewed(1L,2L,8L,3,"fresh",true));
        result.getFuels().add(new PrefillLine());result.getGaps().add("归属待确认");
        assertThrows(ServiceException.class,()->svc.commitReviewed(1L,2L,8L,3,"fresh",false));
        verifyNoInteractions(activities);
    }
}
