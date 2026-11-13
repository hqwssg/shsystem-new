package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.security.CarbonSecurityContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;

/** Company registration intersected with the existing model operation/data scope. */
@Service
public class CompanyOwnershipService {
    public record Company(Long deptId, String deptName) { }
    private final JdbcTemplate jdbc;
    public CompanyOwnershipService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<Company> options() {
        CarbonSecurityContext context = CarbonSecurityContext.current();
        if (!context.hasPermission("carbon:model:edit"))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "没有模型编辑权限");
        return accessibleOptions();
    }

    /** Registered companies visible in the current data scope, without requiring edit permission. */
    public List<Company> accessibleOptions() {
        CarbonSecurityContext context = CarbonSecurityContext.current();
        return registered().stream().filter(c -> context.allData()
                || (!context.selfOnly() && context.deptIds().contains(c.deptId()))).toList();
    }

    public List<Company> registered() {
        return jdbc.query("select d.dept_id,d.dept_name from sys_carbon_company c "
                + "join sys_dept d on d.dept_id=c.dept_id where d.status='0' and d.del_flag='0' order by d.order_num,d.dept_id",
                (row, index) -> new Company(row.getLong(1), row.getString(2)));
    }

    public Long require(Long deptId) {
        if (deptId == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请选择模板归属公司");
        if (options().stream().noneMatch(c -> deptId.equals(c.deptId())))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "公司未登记或不在当前模型授权范围内");
        return deptId;
    }

    /** Used by background calculation without impersonating a logged-in operator. */
    public Long registeredId(Long deptId) {
        return registered().stream().anyMatch(c -> c.deptId().equals(deptId)) ? deptId : null;
    }
}
