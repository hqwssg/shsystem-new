package com.ruoyi.carbon.report.service.impl;

import java.util.Date;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportActivityMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptSubjectMapper;
import com.ruoyi.carbon.report.mapper.ReportTaskMapper;
import com.ruoyi.carbon.report.source.PrefillAssembler;
import com.ruoyi.carbon.report.source.PrefillCommitter;
import com.ruoyi.carbon.report.source.ReportUnitConverter;
import com.ruoyi.carbon.report.source.ReportSubjectSnapshot;
import com.ruoyi.carbon.report.source.ReportCalculationSelection;
import com.ruoyi.carbon.report.source.ReportAllocationScope;
import com.ruoyi.carbon.report.source.ReportSourceSnapshot;
import com.ruoyi.carbon.report.source.ReportPeriodSnapshot;
import com.ruoyi.carbon.report.service.IReportSourceService;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class ReportSourceServiceImpl implements IReportSourceService
{
    @Autowired
    private ReportDeptSubjectMapper subjectMapper;

    @Autowired
    private EmissionCalculationMapper calculationMapper;

    @Autowired
    private ReportActivityMapper activityMapper;

    @Autowired
    private ReportTaskMapper reportTaskMapper;

    @Autowired
    private IReportTaskService reportTaskService;

    private final PrefillAssembler assembler = new PrefillAssembler(new ReportUnitConverter());
    private final PrefillCommitter committer = new PrefillCommitter();

    @Override
    public List<CalculationCandidate> listCalculations(Long deptId, Date periodStart, Date periodEnd)
    {
        if ((periodStart == null) != (periodEnd == null) || (periodStart != null && periodStart.after(periodEnd)))
            throw new ServiceException("报告期间无效", HttpStatus.BAD_REQUEST);
        ReportDeptSubject subject = requireSubject(deptId);
        List<CalculationCandidate> all = ReportCalculationSelection.companyCandidates(calculationMapper,
                deptId, subject.getSubjectNodeId(), periodStart, periodEnd);
        for (CalculationCandidate candidate : all) {
            List<CalculationNodeDataRow> data = calculationMapper.selectNodeData(candidate.getId());
            long abnormal = data == null ? 0 : data.stream().filter(row -> !Integer.valueOf(1).equals(row.getDataStatus())).count();
            String warning = abnormal > 0 ? abnormal + "条核算明细质量待核对；" : "";
            if (periodStart != null && (!java.util.Objects.equals(candidate.getCycleStart(), periodStart) || !java.util.Objects.equals(candidate.getCycleEnd(), periodEnd)))
                warning += "核算期间与筛选期间未完全一致，不会自动截取或分摊";
            candidate.setWarning(warning);
        }
        return assembler.selectable(all);
    }

    @Override
    public PrefillResult preview(Long reportId, Long deptId, Long calculationTemplateId)
    {
        ReportTask task = reportTaskService.get(reportId, deptId);
        ReportDeptSubject current = subjectMapper.selectByDeptId(task.getDeptId());
        ReportDeptSubject subject = ReportSubjectSnapshot.resolve(task, current);
        Long calcId = calculationTemplateId != null ? calculationTemplateId : task.getCalculationTemplateId();
        if (calcId == null)
        {
            throw new ServiceException("请选择核算任务", HttpStatus.BAD_REQUEST);
        }
        if (calculationMapper.selectTask(calcId) == null)
            throw new ServiceException("核算任务" + calcId + "不存在或已删除；原填报已保留，请明确重选数据来源", HttpStatus.BAD_REQUEST);
        ReportPeriodSnapshot.requireSelection(task, calcId, calculationMapper.selectTask(calcId));
        ReportCalculationSelection.requireForReport(calculationMapper, task, subject, calcId,
                task.getPeriodStart(), task.getPeriodEnd());
        List<CalculationNodeDataRow> rows = calculationMapper.selectNodeData(calcId);
        java.util.Set<String> allocations = ReportAllocationScope.accepted(task.getDeptId(), subject,
                current, subjectMapper.selectCompanies(new ReportDeptSubject()));
        PrefillResult result = assembler.assembleForCompany(task.getDeptId(), allocations, rows);
        if (ReportPeriodSnapshot.enabled(task)) {
            result.setSourceSignature(ReportPeriodSnapshot.sourceSignature(rows));
            result.setScopeSignature(ReportPeriodSnapshot.scopeSignature(rows, task.getDeptId(), allocations));
        }
        if (allocations.isEmpty() && rows.stream().noneMatch(row -> task.getDeptId().equals(row.getAttributionCompanyDeptId()))) ReportSourceSnapshot.issue(result, "ALLOCATION_AMBIGUOUS", null,
                "公司表计归属编码未能唯一确定；请核对公司登记映射，不会自动扩大到其他公司", true);
        if (rows.isEmpty()) ReportSourceSnapshot.issue(result, "SOURCE_EMPTY", null, "该任务没有可带入的采集明细，请核对核算结果是否完整", true);
        CalculationCandidate selected = ReportCalculationSelection.forReport(calculationMapper, task, subject,
                task.getPeriodStart(), task.getPeriodEnd()).stream().filter(row -> calcId.equals(row.getId())).findFirst().orElseThrow();
        java.text.SimpleDateFormat format = new java.text.SimpleDateFormat("yyyy-MM-dd");
        if (selected.getCycleStart() != null) result.setCycleStart(format.format(selected.getCycleStart()));
        if (selected.getCycleEnd() != null) result.setCycleEnd(format.format(selected.getCycleEnd()));
        result.setPartialPeriod(!java.util.Objects.equals(result.getCycleStart(), format.format(task.getPeriodStart()))
                || !java.util.Objects.equals(result.getCycleEnd(), format.format(task.getPeriodEnd())));
        result.setReportVersion(task.getVersion());
        result.setPreviewHash(com.ruoyi.carbon.report.generation.SnapshotHasher.sha256(com.alibaba.fastjson2.JSON.toJSONString(result)));
        return result;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public PrefillResult commit(Long reportId, Long deptId, Long calculationTemplateId)
    {
        PrefillResult reviewed = preview(reportId, deptId, calculationTemplateId);
        return commitReviewed(reportId, deptId, calculationTemplateId, reviewed.getReportVersion(), reviewed.getPreviewHash(), false);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public PrefillResult commitReviewed(Long reportId, Long deptId, Long calculationTemplateId,
            Integer version, String previewHash, boolean acceptPartial)
    {
        ReportTask task = reportTaskService.get(reportId, deptId);
        Long calcId = calculationTemplateId != null ? calculationTemplateId : task.getCalculationTemplateId();
        PrefillResult result = preview(reportId, deptId, calcId);
        if (version == null || !version.equals(task.getVersion()) || previewHash == null || !previewHash.equals(result.getPreviewHash()))
            throw new ServiceException("报告或核算来源已变化，请重新预览后带入；原填报未改动", HttpStatus.CONFLICT);
        if (result.getLineCount() == 0)
            throw new ServiceException("没有可带入的活动数据，原填报已保留：" + String.join("；", result.getGaps()), HttpStatus.BAD_REQUEST);
        if ((!result.getGaps().isEmpty() || result.getPartialPeriod()) && !acceptPartial)
            throw new ServiceException("请先核对预览中的缺项和实际核算期间，再确认部分带入；原填报未改动", HttpStatus.BAD_REQUEST);
        // All guards run before any delete; failures leave every stored field intact.
        List<ReportActivityRow> fuels = committer.protectOverrides(task, activityMapper.selectFuels(reportId, deptId),
                committer.toFuelRows(task, result), result.getFuels());
        List<ReportActivityRow> electricity = committer.protectOverrides(task, activityMapper.selectElectricity(reportId, deptId),
                committer.toElectricityRows(task, result), result.getElectricity());
        List<ReportActivityRow> heat = committer.protectOverrides(task, activityMapper.selectHeat(reportId, deptId),
                committer.toHeatRows(task, result), result.getHeat());
        activityMapper.deleteFuels(reportId, deptId);
        activityMapper.deleteElectricity(reportId, deptId);
        activityMapper.deleteHeat(reportId, deptId);
        for (ReportActivityRow row : fuels)
        {
            activityMapper.insertFuel(row);
        }
        for (ReportActivityRow row : electricity)
        {
            activityMapper.insertElectricity(row);
        }
        for (ReportActivityRow row : heat)
        {
            activityMapper.insertHeat(row);
        }
        Integer expected = task.getVersion();
        committer.apply(task, result, calcId);
        ReportSourceSnapshot.freeze(task, result);
        ReportPeriodSnapshot.freezeSource(task, result);
        task.setVersion(expected);
        if (reportTaskMapper.updateWithVersion(task) == 0)
        {
            throw new ServiceException("version conflict", HttpStatus.CONFLICT);
        }
        task.setVersion(expected + 1);
        return result;
    }

    private ReportDeptSubject requireSubject(Long deptId)
    {
        ReportDeptSubject subject = subjectMapper.selectByDeptId(deptId);
        // The subject mapping is data configuration, not an authorization
        // gate.  Older deployments may retain enabled=0 after the permission
        // model was removed; the report workflow must still be usable when a
        // valid subject node is configured.
        ReportSubjectSnapshot.requireAllocation(subject);
        return subject;
    }
}
