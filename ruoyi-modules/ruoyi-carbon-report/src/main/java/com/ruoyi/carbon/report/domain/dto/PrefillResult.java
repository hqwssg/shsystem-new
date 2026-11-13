package com.ruoyi.carbon.report.domain.dto;

import java.util.ArrayList;
import java.util.List;

public class PrefillResult
{
    private String sourceSignature;
    private String scopeSignature;
    public String getSourceSignature() { return sourceSignature; }
    public void setSourceSignature(String value) { sourceSignature = value; }
    public String getScopeSignature() { return scopeSignature; }
    public void setScopeSignature(String value) { scopeSignature = value; }
    private final List<PrefillLine> fuels = new ArrayList<>();
    private final List<PrefillLine> electricity = new ArrayList<>();
    private final List<PrefillLine> heat = new ArrayList<>();
    private final List<java.util.Map<String, Object>> issues = new ArrayList<>();
    public List<java.util.Map<String, Object>> getIssues() { return issues; }
    public int getLineCount() { return fuels.size() + electricity.size() + heat.size(); }
    private final List<String> gaps = new ArrayList<>();

    public List<PrefillLine> getFuels() { return fuels; }
    public List<PrefillLine> getElectricity() { return electricity; }
    public List<PrefillLine> getHeat() { return heat; }
    public List<String> getGaps() { return gaps; }

    private Integer reportVersion;
    public Integer getReportVersion() { return reportVersion; }
    public void setReportVersion(Integer value) { reportVersion = value; }
    private String previewHash;
    public String getPreviewHash() { return previewHash; }
    public void setPreviewHash(String value) { previewHash = value; }
    private String cycleStart;
    public String getCycleStart() { return cycleStart; }
    public void setCycleStart(String value) { cycleStart = value; }
    private String cycleEnd;
    public String getCycleEnd() { return cycleEnd; }
    public void setCycleEnd(String value) { cycleEnd = value; }
    private boolean partialPeriod;
    public boolean getPartialPeriod() { return partialPeriod; }
    public void setPartialPeriod(boolean value) { partialPeriod = value; }
}
