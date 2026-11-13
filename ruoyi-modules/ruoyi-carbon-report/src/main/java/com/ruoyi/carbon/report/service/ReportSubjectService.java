package com.ruoyi.carbon.report.service;

import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportSubjectOption;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.mapper.ReportDeptSubjectMapper;
import com.ruoyi.carbon.report.mapper.ReportTaskMapper;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class ReportSubjectService
{
    private final ReportSubjectQueryService queries;
    private final ReportDeptSubjectMapper subjects;
    private final ReportTaskMapper tasks;
    private final ReportFileMapper files;

    public ReportSubjectService(ReportSubjectQueryService queries, ReportDeptSubjectMapper subjects,
            ReportTaskMapper tasks, ReportFileMapper files)
    {
        this.queries = queries;
        this.subjects = subjects;
        this.tasks = tasks;
        this.files = files;
    }

    public List<ReportSubjectOption> list() { return queries.companies(new ReportDeptSubject()); }

    /** New reports use registered companies without widening the existing report DataScope. */
    public Long requireCompany(Long deptId)
    {
        if (deptId == null) throw new ServiceException("请选择报告公司", 400);
        ReportDeptSubject query = new ReportDeptSubject();
        query.setDeptId(deptId);
        if (queries.companies(query).stream().noneMatch(row -> deptId.equals(row.getDeptId())))
            throw new ServiceException("所选公司未登记或不在报告授权范围内", 403);
        return deptId;
    }

    public Long requireDept(Long deptId)
    {
        if (deptId == null) throw new ServiceException("请选择报告主体", 400);
        ReportDeptSubject query = new ReportDeptSubject();
        query.setDeptId(deptId);
        if (queries.departments(query).stream().noneMatch(row -> deptId.equals(row.getDeptId())))
            throw new ServiceException("无权操作该报告主体", 403);
        return deptId;
    }

    public Long reportDept(Long reportId)
    {
        ReportTask task = tasks.selectById(reportId);
        if (task == null) throw new ServiceException("报告不存在或不可访问", 404);
        return requireDept(task.getDeptId());
    }

    public Long artifactDept(Long fileId)
    {
        ReportFile file = files.selectById(fileId);
        if (file == null) throw new ServiceException("文件不存在或不可访问", 404);
        return requireDept(file.getDeptId());
    }

    public List<ReportSubjectOption> nodes() { return queries.nodes(new ReportDeptSubject()); }

    @Transactional(rollbackFor = Exception.class)
    public void save(Long deptId, ReportDeptSubject subject, String username)
    {
        requireCompany(deptId);
        if (subject == null || subject.getEnergyAllocation() == null
                || !subject.getEnergyAllocation().matches("[a-zA-Z0-9_-]{1,64}"))
            throw new ServiceException("请选择主体节点并填写有效的表计部门归属编码", 400);
        if (subject.getSubjectNodeId() != null && nodes().stream().noneMatch(node -> subject.getSubjectNodeId().equals(node.getSubjectNodeId())))
            throw new ServiceException("主体节点不存在或不在授权范围内", 403);
        // The path and authenticated operator, never client-supplied ownership/audit fields.
        subject.setDeptId(deptId);
        subject.setCreateBy(username);
        subject.setUpdateBy(username);
        subjects.upsert(subject);
    }
}
