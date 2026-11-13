package com.ruoyi.carbon.report.domain;

/** A department's report boundary, or an explicitly selectable design node. */
public class ReportSubjectOption extends ReportDeptSubject
{
    private String deptName;
    private String subjectName;
    private Long templateId;
    private String templateName;

    public String getDeptName() { return deptName; }
    public void setDeptName(String value) { deptName = value; }
    public String getSubjectName() { return subjectName; }
    public void setSubjectName(String value) { subjectName = value; }
    public Long getTemplateId() { return templateId; }
    public void setTemplateId(Long value) { templateId = value; }
    public String getTemplateName() { return templateName; }
    public void setTemplateName(String value) { templateName = value; }
    public boolean isConfigured()
    {
        return getEnergyAllocation() != null && !getEnergyAllocation().isBlank();
    }
}
