package com.ruoyi.system.service.impl;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.Locale;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.util.CollectionUtils;
import com.ruoyi.common.core.constant.Constants;
import com.ruoyi.common.core.constant.UserConstants;
import com.ruoyi.common.core.utils.StringUtils;
import com.ruoyi.system.api.domain.SysRole;
import com.ruoyi.system.api.domain.SysUser;
import com.ruoyi.system.service.ISysMenuService;
import com.ruoyi.system.service.ISysPermissionService;
import com.ruoyi.system.service.ISysRoleService;

/**
 * 用户权限处理
 * 
 * @author ruoyi
 */
@Service
public class SysPermissionServiceImpl implements ISysPermissionService
{
    /** Role keys that represent a platform-wide administrator. Role IDs are
     * deliberately not used because they can change during data migration. */
    private static final Set<String> ADMINISTRATOR_ROLE_KEYS = Set.of(
            "admin", "companyadmin", "systemadmin", "platformadmin", "superadmin",
            "sysadmin", "systemadministrator", "platformadministrator", "companyadministrator");
    private static final Set<String> ADMINISTRATOR_ROLE_NAMES = Set.of(
            "系统管理员", "超级管理员", "平台管理员", "公司级系统管理员", "公司管理员",
            "systemadministrator", "superadministrator", "platformadministrator", "companyadministrator");
    @Autowired
    private ISysRoleService roleService;

    @Autowired
    private ISysMenuService menuService;

    /**
     * 获取角色数据权限
     * 
     * @param userId 用户Id
     * @return 角色权限信息
     */
    @Override
    public Set<String> getRolePermission(SysUser user)
    {
        Set<String> roles = new HashSet<String>();
        // 最高管理员保留全权限能力，但对外返回项目定义的真实角色键。
        Set<String> assignedRoles = roleService.selectRolePermissionByUserId(user.getUserId());
        if (assignedRoles != null)
        {
            roles.addAll(assignedRoles);
        }
        // The role key is the value consumed by the web client.  Imported
        // databases can keep the administrator's display name while using a
        // legacy/non-standard key, so expose the canonical admin role too.
        if (isAdministratorUser(user) || (!CollectionUtils.isEmpty(user.getRoles())
                && user.getRoles().stream().anyMatch(this::isActiveAdministratorRole)))
        {
            roles.add("admin");
        }
        return roles;
    }

    /**
     * 获取菜单数据权限
     * 
     * @param userId 用户Id
     * @return 菜单权限信息
     */
    @Override
    public Set<String> getMenuPermission(SysUser user)
    {
        Set<String> perms = new HashSet<String>();
        List<SysRole> roles = user.getRoles();
        boolean hasActiveAdminRole = !CollectionUtils.isEmpty(roles) && roles.stream().anyMatch(role ->
                isActiveAdministratorRole(role));
        // Keep the administrator contract stable by role key as well as the
        // legacy fixed role id. Production databases can assign a different
        // role_id when the default rows were imported in another order.
        if (isAdministratorUser(user) || hasActiveAdminRole)
        {
            perms.add(Constants.ALL_PERMISSION);
        }
        else
        {
            if (!CollectionUtils.isEmpty(roles))
            {
                // 多角色设置permissions属性，以便数据权限匹配权限
                for (SysRole role : roles)
                {
                    if (StringUtils.equals(role.getStatus(), UserConstants.ROLE_NORMAL)
                            && !isActiveAdministratorRole(role))
                    {
                        Set<String> rolePerms = menuService.selectMenuPermsByRoleId(role.getRoleId());
                        role.setPermissions(rolePerms);
                        perms.addAll(rolePerms);
                    }
                }
            }
            else
            {
                perms.addAll(menuService.selectMenuPermsByUserId(user.getUserId()));
            }
        }
        return perms;
    }

    private boolean isActiveAdministratorRole(SysRole role)
    {
        return role != null
                && StringUtils.equals(role.getStatus(), UserConstants.ROLE_NORMAL)
                && isAdministratorRole(role);
    }

    private boolean isAdministratorUser(SysUser user)
    {
        return user != null && (user.isAdmin()
                || (user.getUserName() != null && "admin".equalsIgnoreCase(user.getUserName().trim())));
    }

    static boolean isAdministratorRoleKey(String roleKey)
    {
        return ADMINISTRATOR_ROLE_KEYS.contains(normalizeAdministratorLabel(roleKey));
    }

    static boolean isAdministratorRoleName(String roleName)
    {
        return ADMINISTRATOR_ROLE_NAMES.contains(normalizeAdministratorLabel(roleName));
    }

    private boolean isAdministratorRole(SysRole role)
    {
        return role != null && (role.isAdmin()
                || isAdministratorRoleKey(role.getRoleKey())
                || isAdministratorRoleName(role.getRoleName()));
    }

    private static String normalizeAdministratorLabel(String value)
    {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT).replaceAll("[\\s_-]+", "");
    }
}
