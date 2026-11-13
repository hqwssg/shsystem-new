package com.ruoyi.carbon.report.source;

import java.util.Date;
import java.util.List;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.common.core.exception.ServiceException;

public final class ReportCalculationSelection
{
    private ReportCalculationSelection() { }

    public static List<CalculationCandidate> companyCandidates(EmissionCalculationMapper mapper, Long company,
            Long legacyNode, Date start, Date end) {
        java.util.Map<Long, CalculationCandidate> rows = new java.util.LinkedHashMap<>();
        List<CalculationCandidate> companyRows = mapper.selectCompanyCandidates(company, start, end);
        if (companyRows != null) for (CalculationCandidate row : companyRows)
            if (company.equals(row.getCompanyDeptId()) && row.isSuccess()) rows.put(row.getId(), row);
        // Explicit legacy mappings remain supported; never let a legacy node override a confirmed company.
        if (legacyNode != null) {
            List<CalculationCandidate> legacy = mapper.selectCandidates(legacyNode, start, end);
            if (legacy != null) for (CalculationCandidate row : legacy)
                if (row.getCompanyDeptId() == null && row.isSuccess()) rows.putIfAbsent(row.getId(), row);
        }
        return rows.values().stream().sorted(java.util.Comparator.comparing(CalculationCandidate::getFinishedAt,
                java.util.Comparator.nullsLast(java.util.Comparator.reverseOrder()))).toList();
    }

    public static List<CalculationCandidate> forReport(EmissionCalculationMapper mapper,
            com.ruoyi.carbon.report.domain.ReportTask task, com.ruoyi.carbon.report.domain.ReportDeptSubject subject,
            Date start, Date end) {
        if (ReportSubjectSnapshot.isCompany(task))
            return companyCandidates(mapper, task.getDeptId(), subject.getSubjectNodeId(), start, end);
        List<CalculationCandidate> rows = mapper.selectCandidates(subject.getSubjectNodeId(), start, end);
        return rows == null ? List.of() : rows.stream().filter(row -> row.getCompanyDeptId() == null
                || task.getDeptId().equals(row.getCompanyDeptId())).toList();
    }

    public static void requireForReport(EmissionCalculationMapper mapper,
            com.ruoyi.carbon.report.domain.ReportTask task, com.ruoyi.carbon.report.domain.ReportDeptSubject subject,
            Long calculationId, Date start, Date end) {
        if (calculationId == null || start == null || end == null || start.after(end))
            throw new ServiceException("请选择有效报告期间和核算任务", 400);
        if (forReport(mapper, task, subject, start, end).stream().noneMatch(row -> row.isSuccess() && calculationId.equals(row.getId())))
            throw new ServiceException("所选任务不属于该报告公司或期间，或尚未确认公司归属，请重新查询", 400);
    }

    public static void require(EmissionCalculationMapper mapper, Long subjectNodeId, Long calculationId,
            Date start, Date end)
    {
        if (calculationId == null) throw new ServiceException("请选择核算任务", 400);
        if (start == null || end == null || start.after(end)) throw new ServiceException("报告期间无效", 400);
        List<CalculationCandidate> candidates = mapper.selectCandidates(subjectNodeId, start, end);
        if (candidates == null || candidates.stream().noneMatch(row -> row.isSuccess()
                && calculationId.equals(row.getId())))
            throw new ServiceException("所选任务不属于该报告主体或期间，或不是成功的核算模板任务，请重新查询", 400);
    }
}
