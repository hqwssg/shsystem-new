package com.ruoyi.carbon.report.mapper;

import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportSubjectOption;
import java.util.List;

public interface ReportDeptSubjectMapper
{
    ReportDeptSubject selectByDeptId(Long deptId);
    List<ReportSubjectOption> selectDepartments(ReportDeptSubject query);
    List<ReportSubjectOption> selectCompanies(ReportDeptSubject query);
    List<ReportSubjectOption> selectNodes(ReportDeptSubject query);
    int upsert(ReportDeptSubject subject);
}
