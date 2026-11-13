package com.ruoyi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Set;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import com.ruoyi.common.core.constant.Constants;
import com.ruoyi.system.api.domain.SysRole;
import com.ruoyi.system.api.domain.SysUser;
import com.ruoyi.system.service.ISysMenuService;
import com.ruoyi.system.service.ISysRoleService;
import com.ruoyi.system.service.impl.SysPermissionServiceImpl;

class SystemAdministratorPermissionTest
{
    private SysPermissionServiceImpl permissionService;
    private ISysMenuService menuService;

    @BeforeEach
    void setUp()
    {
        permissionService = new SysPermissionServiceImpl();
        menuService = mock(ISysMenuService.class);
        ReflectionTestUtils.setField(permissionService, "menuService", menuService);
        ReflectionTestUtils.setField(permissionService, "roleService", mock(ISysRoleService.class));
    }

    @Test
    void activeAdministratorRoleReceivesAllPermissionsForNonDefaultUserId()
    {
        SysUser user = user(88L, role(88L, "admin", "0"));

        assertEquals(Set.of(Constants.ALL_PERMISSION), permissionService.getMenuPermission(user));
    }

    @Test
    void companyAdministratorRoleReceivesAllPermissionsWhenRoleIdWasMigrated()
    {
        SysUser user = user(88L, role(88L, "company_admin", "0"));

        assertEquals(Set.of(Constants.ALL_PERMISSION), permissionService.getMenuPermission(user));
    }

    @Test
    void migratedChineseAdministratorRoleNameReceivesAllPermissions()
    {
        SysRole role = role(188L, "legacy_role", "0");
        role.setRoleName("系统管理员");
        SysUser user = user(88L, role);

        assertEquals(Set.of(Constants.ALL_PERMISSION), permissionService.getMenuPermission(user));
        assertTrue(permissionService.getRolePermission(user).contains("admin"));
        assertTrue(user.isAdmin());
    }

    @Test
    void disabledChineseAdministratorRoleNameDoesNotGrantAllPermissions()
    {
        SysRole role = role(188L, "legacy_role", "1");
        role.setRoleName("系统管理员");
        SysUser user = user(88L, role);

        assertTrue(permissionService.getMenuPermission(user).isEmpty());
        assertTrue(!permissionService.getRolePermission(user).contains("admin"));
    }

    @Test
    void canonicalAdminLoginReceivesAllPermissionsWhenRoleBindingIsLegacy()
    {
        SysUser user = user(88L, role(88L, "common", "0"));
        user.setUserName("admin");

        assertEquals(Set.of(Constants.ALL_PERMISSION), permissionService.getMenuPermission(user));
    }

    @Test
    void disabledAdministratorRoleDoesNotGrantAllPermissions()
    {
        SysUser user = user(88L, role(88L, "admin", "1"));

        assertTrue(permissionService.getMenuPermission(user).isEmpty());
    }

    @Test
    void ordinaryRoleStillUsesItsAssignedMenuPermissions()
    {
        SysRole role = role(8L, "carbon_accountant", "0");
        SysUser user = user(88L, role);
        when(menuService.selectMenuPermsByRoleId(8L)).thenReturn(Set.of("carbon:prediction:view"));

        assertEquals(Set.of("carbon:prediction:view"), permissionService.getMenuPermission(user));
        verify(menuService).selectMenuPermsByRoleId(8L);
    }

    private SysUser user(Long userId, SysRole role)
    {
        SysUser user = new SysUser();
        user.setUserId(userId);
        user.setRoles(List.of(role));
        return user;
    }

    private SysRole role(Long roleId, String roleKey, String status)
    {
        SysRole role = new SysRole();
        role.setRoleId(roleId);
        role.setRoleKey(roleKey);
        role.setStatus(status);
        return role;
    }
}
