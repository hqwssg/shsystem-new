package com.ruoyi.carbon.report.domain.dto;

public class CreateReportRequest
{
    private String requestKey;
    public String getRequestKey() { return requestKey; }
    public void setRequestKey(String value) { requestKey = value; }
    private String periodMode;
    private String periodStart;
    private String periodEnd;
    public String getPeriodMode() { return periodMode; }
    public void setPeriodMode(String value) { periodMode = value; }
    public String getPeriodStart() { return periodStart; }
    public void setPeriodStart(String value) { periodStart = value; }
    public String getPeriodEnd() { return periodEnd; }
    public void setPeriodEnd(String value) { periodEnd = value; }
    private String title;
    private String periodType;
    private Integer reportYear;
    private Integer reportMonth;
    private Long calculationTemplateId;
    private Long deptId;

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getPeriodType() { return periodType; }
    public void setPeriodType(String periodType) { this.periodType = periodType; }
    public Integer getReportYear() { return reportYear; }
    public void setReportYear(Integer reportYear) { this.reportYear = reportYear; }
    public Integer getReportMonth() { return reportMonth; }
    public void setReportMonth(Integer reportMonth) { this.reportMonth = reportMonth; }
    public Long getCalculationTemplateId() { return calculationTemplateId; }
    public void setCalculationTemplateId(Long calculationTemplateId) { this.calculationTemplateId = calculationTemplateId; }
    public Long getDeptId() { return deptId; }
    public void setDeptId(Long deptId) { this.deptId = deptId; }

    private Integer version;
    public Integer getVersion() { return version; }
    public void setVersion(Integer value) { version = value; }
    private String previewHash;
    public String getPreviewHash() { return previewHash; }
    public void setPreviewHash(String value) { previewHash = value; }
    private Boolean acceptPartial;
    public Boolean getAcceptPartial() { return acceptPartial; }
    public void setAcceptPartial(Boolean value) { acceptPartial = value; }
    private Boolean deferPrefill;
    public Boolean getDeferPrefill() { return deferPrefill; }
    public void setDeferPrefill(Boolean value) { deferPrefill = value; }
}
