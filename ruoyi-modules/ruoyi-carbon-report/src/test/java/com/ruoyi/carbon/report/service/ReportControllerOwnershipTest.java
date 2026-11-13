package com.ruoyi.carbon.report.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.io.ByteArrayInputStream;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import com.ruoyi.carbon.report.controller.ReportTaskController;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.common.core.constant.SecurityConstants;
import com.ruoyi.common.core.context.SecurityContextHolder;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.system.api.domain.SysUser;
import com.ruoyi.system.api.model.LoginUser;

class ReportControllerOwnershipTest
{
    private ReportTaskController controller;
    private ReportSubjectService subjects;
    private IReportTaskService tasks;
    private IReportSourceService source;
    private IReportGenerationService generation;

    @BeforeEach void setup()
    {
        controller = new ReportTaskController(); subjects = mock(ReportSubjectService.class);
        tasks = mock(IReportTaskService.class); source = mock(IReportSourceService.class); generation = mock(IReportGenerationService.class);
        ReflectionTestUtils.setField(controller, "reportSubjects", subjects);
        ReflectionTestUtils.setField(controller, "reportTaskService", tasks);
        ReflectionTestUtils.setField(controller, "reportSourceService", source);
        ReflectionTestUtils.setField(controller, "reportGenerationService", generation);
        SysUser user = new SysUser(); user.setUserId(1L); user.setDeptId(3000L);
        LoginUser login = new LoginUser(); login.setSysUser(user);
        SecurityContextHolder.set(SecurityConstants.LOGIN_USER, login);
        SecurityContextHolder.setUserName("admin");
    }

    @AfterEach void clear() { SecurityContextHolder.remove(); }

    @Test void ordinaryReportUserCannotSaveGlobalAiDefaults()
    {
        SysUser user = new SysUser(); user.setUserId(99L); user.setDeptId(301L); user.setUserName("report-user");
        LoginUser login = new LoginUser(); login.setUserid(99L); login.setSysUser(user);
        SecurityContextHolder.set(SecurityConstants.LOGIN_USER, login);
        ReportLlmConfigService config = mock(ReportLlmConfigService.class);
        ReflectionTestUtils.setField(controller, "reportLlmConfigService", config);
        ServiceException ex = assertThrows(ServiceException.class,
                () -> controller.saveLlmConfigDefault(java.util.Map.of("model", "model-a")));
        assertEquals(403, ex.getCode());
        verifyNoInteractions(config);
    }

    @Test void aiConnectionFailureBlocksValidationAndNonAiDoesNotCallModel()
    {
        when(subjects.reportDept(33L)).thenReturn(303L);
        ReportPreflight preflight = mock(ReportPreflight.class);
        ReportLlmConfigService config = mock(ReportLlmConfigService.class);
        ReflectionTestUtils.setField(controller, "reportPreflight", preflight);
        ReflectionTestUtils.setField(controller, "reportLlmConfigService", config);
        when(preflight.inspect(any())).thenAnswer(i -> {
            java.util.Map<String,Object> result = new java.util.HashMap<>();
            result.put("ok", true); result.put("mustFix", new java.util.ArrayList<String>()); return result;
        });
        doThrow(new ServiceException("模型不可达")).when(generation).testLlmConnection(any());
        java.util.Map<?,?> result = (java.util.Map<?,?>) controller.validate(33L, java.util.Map.of("aiEnabled", true)).get("data");
        assertEquals(false, result.get("ok")); assertEquals(false, result.get("llmReady"));
        clearInvocations(generation, config);
        controller.validate(33L, null);
        verifyNoInteractions(generation, config);
    }

    @Test void ReadSaveDeleteAndPreviewUseStoredReportOwner()
    {
        when(subjects.reportDept(33L)).thenReturn(303L);
        controller.get(33L); controller.draft(33L); controller.remove(33L); controller.prefillPreview(33L, null);
        verify(tasks).get(33L, 303L); verify(tasks).getDraft(33L, 303L);
        verify(tasks).remove(33L, 303L, "admin"); verify(source).preview(33L, 303L, null);
        verify(subjects, never()).requireDept(3000L);
    }

    @Test void UnauthorizedOwnerStopsBeforeBusinessRead()
    {
        when(subjects.reportDept(33L)).thenThrow(new ServiceException("forbidden", 403));
        assertThrows(ServiceException.class, () -> controller.get(33L));
        verifyNoInteractions(tasks);
    }

    @Test void DownloadUsesFileOwnerRatherThanLoginDepartment()
    {
        when(subjects.artifactDept(44L)).thenReturn(303L);
        ReportFile file = new ReportFile(); file.setOriginalName("report.docx");
        when(generation.downloadMeta(44L, 303L)).thenReturn(file);
        when(generation.downloadStream(44L, 303L)).thenReturn(new ByteArrayInputStream(new byte[] {1}));
        assertEquals(200, controller.download(44L).getStatusCode().value());
        verify(generation).downloadStream(44L, 303L);
        verify(subjects, never()).reportDept(44L);
    }

    @Test void ExplicitDepartmentQueryIsAuthorizedAndListNoLongerForcesLoginDepartment()
    {
        when(subjects.requireCompany(303L)).thenReturn(303L);
        java.util.Date start = new java.util.Date(0), end = new java.util.Date(1);
        controller.calculations(start, end, 303L);
        verify(source).listCalculations(303L, start, end);
        ReportTask query = new ReportTask(); controller.list(query);
        assertNull(query.getDeptId()); verify(tasks).list(query);
    }
    @Test void UnregisteredOrUnauthorizedCompanyCannotQueryOrCreateEvenWithForgedRequest()
    {
        when(subjects.requireCompany(999L)).thenThrow(new ServiceException("forbidden", 403));
        com.ruoyi.carbon.report.domain.dto.CreateReportRequest request =
                new com.ruoyi.carbon.report.domain.dto.CreateReportRequest();
        request.setDeptId(999L);
        assertThrows(ServiceException.class, () -> controller.create(request));
        assertThrows(ServiceException.class, () -> controller.calculations(new java.util.Date(0), new java.util.Date(1), 999L));
        verifyNoInteractions(tasks, source);
    }

}
