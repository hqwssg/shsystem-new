package com.ruoyi.carbon.report.source;

import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.common.core.exception.ServiceException;

/** Preserve the report boundary in existing metadata; changing a mapping never rebinds a report. */
public final class ReportSubjectSnapshot
{
    public static final String KEY = "_report_subject";
    private ReportSubjectSnapshot() { }

    public static boolean isCompany(ReportTask task) {
        JSONObject snapshot = metadata(task.getMetadataJson()).getJSONObject(KEY);
        return snapshot != null && "COMPANY".equals(snapshot.getString("mode"));
    }

    public static void freezeCompany(ReportTask task, ReportDeptSubject subject) {
        requireAllocation(subject);
        task.setSubjectNodeId(subject.getSubjectNodeId());
        JSONObject metadata = metadata(task.getMetadataJson());
        JSONObject snapshot = new JSONObject();
        snapshot.put("mode", "COMPANY");
        snapshot.put("deptId", task.getDeptId());
        snapshot.put("subjectNodeId", subject.getSubjectNodeId());
        snapshot.put("energyAllocation", subject.getEnergyAllocation());
        metadata.put(KEY, snapshot); task.setMetadataJson(metadata.toJSONString());
    }

    public static void requireAllocation(ReportDeptSubject subject) {
        if (subject == null || subject.getEnergyAllocation() == null || subject.getEnergyAllocation().isBlank())
            throw new ServiceException("所选公司未配置表计归属编码，请联系管理员", 400);
    }

    public static void freeze(ReportTask task, ReportDeptSubject subject)
    {
        require(subject);
        task.setSubjectNodeId(subject.getSubjectNodeId());
        JSONObject metadata = metadata(task.getMetadataJson());
        JSONObject snapshot = new JSONObject();
        snapshot.put("deptId", task.getDeptId());
        snapshot.put("subjectNodeId", subject.getSubjectNodeId());
        snapshot.put("energyAllocation", subject.getEnergyAllocation());
        metadata.put(KEY, snapshot);
        task.setMetadataJson(metadata.toJSONString());
    }

    public static ReportDeptSubject resolve(ReportTask task, ReportDeptSubject current)
    {
        JSONObject snapshot = metadata(task.getMetadataJson()).getJSONObject(KEY);
        ReportDeptSubject subject = new ReportDeptSubject();
        subject.setDeptId(task.getDeptId());
        if (snapshot != null)
        {
            subject.setSubjectNodeId(task.getSubjectNodeId());
            subject.setEnergyAllocation(snapshot.getString("energyAllocation"));
        }
        else
        {
            // Legacy reports have a saved node but no allocation snapshot. Never silently
            // import from a newly configured node after an administrator changes the mapping.
            if (task.getSubjectNodeId() != null && (current == null
                    || !task.getSubjectNodeId().equals(current.getSubjectNodeId())))
                throw new ServiceException("该历史报告主体与当前配置不同，请保留已有数据或新建报告", 400);
            subject.setSubjectNodeId(task.getSubjectNodeId() != null ? task.getSubjectNodeId()
                    : current == null ? null : current.getSubjectNodeId());
            subject.setEnergyAllocation(current == null ? null : current.getEnergyAllocation());
        }
        if (isCompany(task)) requireAllocation(subject); else require(subject);
        return subject;
    }

    public static String preserveOnBasicSave(String existing, String incoming)
    {
        JSONObject original = metadata(existing);
        JSONObject replacement = metadata(incoming);
        replacement.keySet().removeIf(key -> key.startsWith("_"));
        original.forEach((key, value) -> { if (key.startsWith("_")) replacement.put(key, value); });
        return replacement.toJSONString();
    }

    public static void require(ReportDeptSubject subject)
    {
        if (subject == null || subject.getSubjectNodeId() == null || subject.getEnergyAllocation() == null
                || subject.getEnergyAllocation().isBlank())
            throw new ServiceException("所选部门未完整配置报告主体节点和表计部门归属，请联系管理员", 400);
    }

    private static JSONObject metadata(String value)
    {
        return value == null || value.isBlank() ? new JSONObject() : JSON.parseObject(value);
    }
}
