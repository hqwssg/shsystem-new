package com.ruoyi.carbon.report.service;

import java.util.List;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportSubjectOption;
import com.ruoyi.carbon.report.mapper.ReportDeptSubjectMapper;
import com.ruoyi.common.core.context.SecurityContextHolder;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.datascope.annotation.DataScope;
import com.ruoyi.common.security.utils.SecurityUtils;

/** Uses the existing role/department DataScope and the current operation permission. */
@Service
public class ReportSubjectQueryService
{
    private final ReportDeptSubjectMapper mapper;

    public ReportSubjectQueryService(ReportDeptSubjectMapper mapper) { this.mapper = mapper; }

    @DataScope(deptAlias = "d")
    public List<ReportSubjectOption> departments(ReportDeptSubject query)
    {
        requireContext();
        return mapper.selectDepartments(query);
    }

    @DataScope(deptAlias = "t")
    public List<ReportSubjectOption> nodes(ReportDeptSubject query)
    {
        requireContext();
        return mapper.selectNodes(query);
    }

    @DataScope(deptAlias = "d")
    public List<ReportSubjectOption> companies(ReportDeptSubject query)
    {
        requireContext();
        return mapper.selectCompanies(query);
    }

    private void requireContext()
    {
        if (SecurityUtils.getLoginUser() == null || SecurityUtils.getLoginUser().getSysUser() == null
                || SecurityContextHolder.getPermission() == null
                || !SecurityContextHolder.getPermission().startsWith("carbon:report:"))
        {
            throw new ServiceException("无报告操作权限", 403);
        }
    }
}
