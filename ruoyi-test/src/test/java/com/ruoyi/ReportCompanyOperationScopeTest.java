package com.ruoyi;

import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import com.ruoyi.admin.controller.internal.IntegratedSecurityContextController;
import com.ruoyi.system.service.*;
import com.ruoyi.system.api.domain.*;
import com.ruoyi.system.api.model.LoginUser;
import com.ruoyi.common.core.context.SecurityContextHolder;
import com.ruoyi.common.core.constant.SecurityConstants;
import org.springframework.jdbc.core.JdbcTemplate;

class ReportCompanyOperationScopeTest {
    private IntegratedSecurityContextController controller;
    private SysUser user;
    private ISysPermissionService permissions;
    @BeforeEach void setup() {
        ISysUserService users=mock(ISysUserService.class); permissions=mock(ISysPermissionService.class);
        controller=new IntegratedSecurityContextController(users,mock(ISysDeptService.class),permissions,mock(JdbcTemplate.class));
        user=new SysUser();user.setUserId(8L);user.setDeptId(302L);user.setStatus("0");user.setDelFlag("0");
        LoginUser login=new LoginUser();login.setSysUser(user);login.setUserid(user.getUserId());SecurityContextHolder.set(SecurityConstants.LOGIN_USER,login);
        when(users.selectUserById(8L)).thenReturn(user);
        when(permissions.getMenuPermission(user)).thenReturn(Set.of("carbon:model:view","carbon:model:edit"));
        when(permissions.getRolePermission(user)).thenReturn(Set.of());
    }
    @AfterEach void clear(){SecurityContextHolder.remove();}
    private SysRole role(String scope,String permission) {
        SysRole role=new SysRole();role.setRoleId(88L);role.setStatus("0");role.setDataScope(scope);role.setPermissions(Set.of(permission));return role;
    }
    @Test void BroadReadRoleDoesNotExpandCompanySelectionOrCreationScope() {
        user.setRoles(List.of(role("1","carbon:model:view"),role("3","carbon:model:edit")));
        var result=controller.context("carbon:model:edit"); assertEquals(200,result.getCode());
        assertEquals(false,result.getData().get("allData"));assertEquals(List.of(302L),result.getData().get("deptIds"));
        assertEquals("carbon:model:edit",result.getData().get("scopePermission"));
        assertEquals(true,controller.context().getData().get("allData"));
    }
    @Test void SelfOnlyAndDisabledRolesDoNotGainCompanyWideScope() {
        SysRole disabled=role("1","carbon:model:edit");disabled.setStatus("1");
        user.setRoles(List.of(disabled,role("5","carbon:model:edit")));
        var result=controller.context("carbon:model:edit");assertEquals(false,result.getData().get("allData"));assertEquals(true,result.getData().get("selfOnly"));
    }
    @Test void MissingOperationPermissionAndMissingIdentityAreRejected() {
        user.setRoles(List.of(role("1","carbon:model:view")));
        when(permissions.getMenuPermission(user)).thenReturn(Set.of("carbon:model:view"));assertEquals(403,controller.context("carbon:model:edit").getCode());
        user.setUserId(1L);LoginUser login=new LoginUser();login.setSysUser(user);login.setUserid(user.getUserId());SecurityContextHolder.set(SecurityConstants.LOGIN_USER,login);
        // The identity lookup remains authoritative even for admin.
        assertEquals(401,controller.context("carbon:model:edit").getCode());
    }

    @Test void ActiveCompanyAdministratorDoesNotDependOnMenuRowsForOperationAccess() {
        user.setUserId(8L);
        SysRole administrator = role("1", "carbon:model:view");
        administrator.setRoleKey("company_admin");
        user.setRoles(List.of(administrator));
        when(permissions.getMenuPermission(user)).thenReturn(Set.of());

        var result = controller.context("carbon:prediction:forecast");

        assertEquals(200, result.getCode());
        assertEquals(true, result.getData().get("allData"));
    }
}
