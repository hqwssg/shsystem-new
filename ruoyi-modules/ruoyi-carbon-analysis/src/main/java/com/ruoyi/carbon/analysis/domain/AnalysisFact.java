package com.ruoyi.carbon.analysis.domain;

import java.math.BigDecimal;

public class AnalysisFact
{
    private Long templateId;
    private String cycleStart;
    private String cycleEnd;
    private String calculationEndTime;
    private Long calcNodeId;
    private Long sourceNodeId;
    private String nodeName;
    private String nodeCategory;
    private String energyCategoryL1;
    private String energyCategoryL2;
    private String energyCategoryL3;
    private String subcategory;
    private String subcategoryName;
    private String unitCode;
    private String unitName;
    private BigDecimal energyValue;
    private BigDecimal carbonValue;

    public Long getTemplateId() { return templateId; }
    public void setTemplateId(Long templateId) { this.templateId = templateId; }
    public String getCycleStart() { return cycleStart; }
    public void setCycleStart(String cycleStart) { this.cycleStart = cycleStart; }
    public String getCycleEnd() { return cycleEnd; }
    public void setCycleEnd(String cycleEnd) { this.cycleEnd = cycleEnd; }
    public String getCalculationEndTime() { return calculationEndTime; }
    public void setCalculationEndTime(String calculationEndTime) { this.calculationEndTime = calculationEndTime; }
    public Long getCalcNodeId() { return calcNodeId; }
    public void setCalcNodeId(Long calcNodeId) { this.calcNodeId = calcNodeId; }
    public Long getSourceNodeId() { return sourceNodeId; }
    public void setSourceNodeId(Long sourceNodeId) { this.sourceNodeId = sourceNodeId; }
    public String getNodeName() { return nodeName; }
    public void setNodeName(String nodeName) { this.nodeName = nodeName; }
    public String getNodeCategory() { return nodeCategory; }
    public void setNodeCategory(String nodeCategory) { this.nodeCategory = nodeCategory; }
    public String getEnergyCategoryL1() { return energyCategoryL1; }
    public void setEnergyCategoryL1(String energyCategoryL1) { this.energyCategoryL1 = energyCategoryL1; }
    public String getEnergyCategoryL2() { return energyCategoryL2; }
    public void setEnergyCategoryL2(String energyCategoryL2) { this.energyCategoryL2 = energyCategoryL2; }
    public String getEnergyCategoryL3() { return energyCategoryL3; }
    public void setEnergyCategoryL3(String energyCategoryL3) { this.energyCategoryL3 = energyCategoryL3; }
    public String getSubcategory() { return subcategory; }
    public void setSubcategory(String subcategory) { this.subcategory = subcategory; }
    public String getSubcategoryName() { return subcategoryName; }
    public void setSubcategoryName(String subcategoryName) { this.subcategoryName = subcategoryName; }
    public String getUnitCode() { return unitCode; }
    public void setUnitCode(String unitCode) { this.unitCode = unitCode; }
    public String getUnitName() { return unitName; }
    public void setUnitName(String unitName) { this.unitName = unitName; }
    public BigDecimal getEnergyValue() { return energyValue; }
    public void setEnergyValue(BigDecimal energyValue) { this.energyValue = energyValue; }
    public BigDecimal getCarbonValue() { return carbonValue; }
    public void setCarbonValue(BigDecimal carbonValue) { this.carbonValue = carbonValue; }
}
