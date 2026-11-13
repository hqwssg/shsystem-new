package com.example.carbon.emission.model.security;

import java.util.Collections;
import java.util.List;
import java.util.Set;

/** Login and data-scope information supplied by the RuoYi admin service. */
public record UncertaintySecurityContext(
        Long userId,
        String userName,
        Long deptId,
        Set<String> roles,
        Set<String> permissions,
        boolean allData,
        boolean selfOnly,
        List<Long> deptIds) {

    public static final String REQUEST_ATTRIBUTE = UncertaintySecurityContext.class.getName();

    public boolean hasPermission(String required) {
        if (required == null || required.isBlank()) return true;
        if (permissions == null) return false;
        return permissions.stream().anyMatch(granted -> "*:*:*".equals(granted)
                || required.equals(granted)
                || (granted.endsWith(":*") && required.startsWith(granted.substring(0, granted.length() - 1)))
                || (granted.endsWith("*") && required.startsWith(granted.substring(0, granted.length() - 1))));
    }

    public List<Long> effectiveDeptIds() {
        return deptIds == null ? Collections.emptyList() : deptIds;
    }
}
