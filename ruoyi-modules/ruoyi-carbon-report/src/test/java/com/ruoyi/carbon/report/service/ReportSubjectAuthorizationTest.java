package com.ruoyi.carbon.report.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.aspectj.annotation.AspectJProxyFactory;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.mapper.*;
import com.ruoyi.common.core.constant.SecurityConstants;
import com.ruoyi.common.core.context.SecurityContextHolder;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.datascope.aspect.DataScopeAspect;
import com.ruoyi.system.api.domain.SysRole;
import com.ruoyi.system.api.domain.SysUser;
import com.ruoyi.system.api.model.LoginUser;

class ReportSubjectAuthorizationTest
{
    private ReportDeptSubjectMapper mapper;
    private ReportSubjectQueryService queries;

    @BeforeEach void setup()
    {
        mapper = mock(ReportDeptSubjectMapper.class);
        AspectJProxyFactory proxy = new AspectJProxyFactory(new ReportSubjectQueryService(mapper));
        proxy.addAspect(new DataScopeAspect());
        queries = proxy.getProxy();
        when(mapper.selectDepartments(any())).thenReturn(List.of());
        when(mapper.selectNodes(any())).thenReturn(List.of());
        when(mapper.selectCompanies(any())).thenReturn(List.of());
        login(8L, "3", "carbon:report:query", "0");
    }

    @AfterEach void clear() { SecurityContextHolder.remove(); }

    private void login(Long id, String scope, String permission, String status)
    {
        SysRole role = new SysRole();
        role.setRoleId(88L); role.setDataScope(scope); role.setStatus(status);
        role.setPermissions(Set.of(permission));
        SysUser user = new SysUser();
        user.setUserId(id); user.setDeptId(3000L); user.setRoles(List.of(role));
        LoginUser login = new LoginUser(); login.setSysUser(user);
        SecurityContextHolder.set(SecurityConstants.LOGIN_USER, login);
        SecurityContextHolder.setPermission("carbon:report:query");
    }

    @Test void ownDepartmentAndForgedScopeAreFilteredByExistingAspect()
    {
        ReportDeptSubject query = new ReportDeptSubject();
        query.getParams().put("dataScope", " OR 1=1");
        queries.companies(query);
        String sql = String.valueOf(query.getParams().get("dataScope"));
        assertTrue(sql.contains("d.dept_id = 3000"));
        assertFalse(sql.contains("1=1"));
    }

    @Test void parentAndChildrenUseExistingDepartmentAncestry()
    {
        login(8L, "4", "carbon:report:query", "0");
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("find_in_set( 3000 , ancestors )"));
    }

    @Test void customRoleUsesRoleDepartmentTable()
    {
        login(8L, "2", "carbon:report:query", "0");
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("sys_role_dept WHERE role_id = 88"));
    }

    @Test void allDataRoleAndSuperAdminUseExistingRules()
    {
        login(8L, "1", "carbon:report:query", "0");
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        assertEquals("", query.getParams().get("dataScope"));
        login(1L, "3", "carbon:report:query", "0");
        query = new ReportDeptSubject(); queries.companies(query);
        assertEquals("", query.getParams().get("dataScope"));
    }

    @Test void BroadRoleForUnrelatedOperationDoesNotGrantReportAccess()
    {
        login(8L, "1", "system:user:list", "0");
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("d.dept_id = 0"));
    }

    @Test void DisabledRoleAndSelfOnlyDoNotGrantOtherDepartments()
    {
        login(8L, "1", "carbon:report:query", "1");
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("d.dept_id = 0"));
        login(8L, "5", "carbon:report:query", "0");
        query = new ReportDeptSubject(); queries.companies(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("d.dept_id = 0"));
    }

    @Test void NodeOptionsAreScopedByTemplateDepartment()
    {
        ReportDeptSubject query = new ReportDeptSubject(); queries.nodes(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("t.dept_id = 3000"));
    }

    @Test void MissingAuthenticationFailsClosed()
    {
        SecurityContextHolder.remove();
        assertThrows(ServiceException.class, () -> queries.departments(new ReportDeptSubject()));
        verify(mapper, never()).selectDepartments(any());
    }

    @Test void ResourceAccessUsesStoredOwnerAndCurrentOperationScope()
    {
        ReportSubjectQueryService scoped = mock(ReportSubjectQueryService.class);
        ReportTaskMapper tasks = mock(ReportTaskMapper.class);
        ReportFileMapper files = mock(ReportFileMapper.class);
        ReportSubjectService service = new ReportSubjectService(scoped, mapper, tasks, files);
        ReportSubjectOption allowed = new ReportSubjectOption(); allowed.setDeptId(303L);
        when(scoped.departments(any())).thenReturn(List.of(allowed));
        ReportTask report = new ReportTask(); report.setDeptId(303L);
        when(tasks.selectById(10L)).thenReturn(report);
        assertEquals(303L, service.reportDept(10L));
        ReportFile file = new ReportFile(); file.setDeptId(302L);
        when(files.selectById(11L)).thenReturn(file);
        assertEquals(403, assertThrows(ServiceException.class, () -> service.artifactDept(11L)).getCode());
        assertEquals(404, assertThrows(ServiceException.class, () -> service.reportDept(999L)).getCode());
    }

    @Test void ExplicitMappingSaveRequiresBothDepartmentAndNodeAuthority()
    {
        ReportSubjectQueryService scoped = mock(ReportSubjectQueryService.class);
        ReportSubjectService service = new ReportSubjectService(scoped, mapper, mock(ReportTaskMapper.class), mock(ReportFileMapper.class));
        ReportSubjectOption allowed = new ReportSubjectOption(); allowed.setDeptId(303L); allowed.setSubjectNodeId(3171L);
        when(scoped.departments(any())).thenReturn(List.of(allowed));
        when(scoped.nodes(any())).thenReturn(List.of(allowed));
        when(scoped.companies(any())).thenReturn(List.of(allowed));
        ReportDeptSubject input = new ReportDeptSubject();
        input.setSubjectNodeId(3171L); input.setEnergyAllocation("jilong"); input.setDeptId(999L);
        service.save(303L, input, "admin");
        assertEquals(303L, input.getDeptId()); assertEquals("admin", input.getUpdateBy());
        verify(mapper).upsert(input);
        input.setSubjectNodeId(999L);
        assertThrows(ServiceException.class, () -> service.save(303L, input, "admin"));
        input.setEnergyAllocation("jilong' OR 1=1");
        assertThrows(ServiceException.class, () -> service.save(303L, input, "admin"));
        verify(mapper, times(1)).upsert(any());
    }
    @Test void CompanyMembershipAndReportScopeAreBothRequiredButLegacyReadRemainsAllowed()
    {
        ReportSubjectQueryService scoped = mock(ReportSubjectQueryService.class);
        ReportSubjectService service = new ReportSubjectService(scoped, mapper,
                mock(ReportTaskMapper.class), mock(ReportFileMapper.class));
        ReportSubjectOption department = new ReportSubjectOption(); department.setDeptId(303L);
        when(scoped.departments(any())).thenReturn(List.of(department));
        when(scoped.companies(any())).thenReturn(List.of());
        assertEquals(303L, service.requireDept(303L));
        assertEquals(403, assertThrows(ServiceException.class, () -> service.requireCompany(303L)).getCode());
        assertEquals(400, assertThrows(ServiceException.class, () -> service.requireCompany(null)).getCode());
        when(scoped.companies(any())).thenReturn(List.of(department));
        assertEquals(303L, service.requireCompany(303L));
        assertEquals(403, assertThrows(ServiceException.class, () -> service.requireCompany(302L)).getCode());
        assertEquals(1, service.list().size());
    }

    @Test void CompanyQueryRequiresReportAuthenticationAndDoesNotPromoteDepartmentToParentCompany()
    {
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        String sql = query.getParams().get("dataScope").toString();
        assertTrue(sql.contains("d.dept_id = 3000"));
        assertFalse(sql.contains("ancestors"));
        SecurityContextHolder.remove();
        assertThrows(ServiceException.class, () -> queries.companies(new ReportDeptSubject()));
        verify(mapper, times(1)).selectCompanies(any());
    }

    @Test void CompanyOptionsUseCreateScopeRatherThanAnUnrelatedBroaderReadRole()
    {
        login(8L, "3", "carbon:report:add", "0");
        SysUser user = com.ruoyi.common.security.utils.SecurityUtils.getLoginUser().getSysUser();
        SysRole reader = new SysRole();
        reader.setRoleId(99L); reader.setDataScope("1"); reader.setStatus("0");
        reader.setPermissions(Set.of("carbon:report:list"));
        user.setRoles(List.of(user.getRoles().get(0), reader));
        SecurityContextHolder.setPermission("carbon:report:add");
        ReportDeptSubject query = new ReportDeptSubject(); queries.companies(query);
        assertTrue(query.getParams().get("dataScope").toString().contains("d.dept_id = 3000"));
    }

}
