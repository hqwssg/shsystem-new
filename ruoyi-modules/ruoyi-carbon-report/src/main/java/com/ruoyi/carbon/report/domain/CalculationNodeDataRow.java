package com.ruoyi.carbon.report.domain;

import java.math.BigDecimal;

public class CalculationNodeDataRow
{
    private Long id;
    private Long calculationTemplateId;
    private String emissionCategory;
    private String emissionSubcategory;
    private BigDecimal energyMeasurementValue;
    private BigDecimal adjustedEnergyValue;
    private BigDecimal carbonEmission;
    private String measurementUnit;
    private Long collectionPointId;
    private Integer collectionPointType;
    private String energyAllocation;
    // Null on legacy schemas. Keep the raw department as evidence even if it cannot resolve.
    private Long attributionDeptId;
    private Long attributionCompanyDeptId;
    public Long getAttributionDeptId() { return attributionDeptId; }
    public void setAttributionDeptId(Long value) { attributionDeptId = value; }
    public Long getAttributionCompanyDeptId() { return attributionCompanyDeptId; }
    public void setAttributionCompanyDeptId(Long value) { attributionCompanyDeptId = value; }
    private String facilityName;
    private Integer status;

    public BigDecimal preferredEnergyValue()
    {
        return adjustedEnergyValue != null ? adjustedEnergyValue : energyMeasurementValue;
    }

    public BigDecimal preferredCarbonValue()
    {
        return adjustedEnergyValue != null ? adjustedCarbonEmission : carbonEmission;
    }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getCalculationTemplateId() { return calculationTemplateId; }
    public void setCalculationTemplateId(Long calculationTemplateId) { this.calculationTemplateId = calculationTemplateId; }
    public String getEmissionCategory() { return emissionCategory; }
    public void setEmissionCategory(String emissionCategory) { this.emissionCategory = emissionCategory; }
    public String getEmissionSubcategory() { return emissionSubcategory; }
    public void setEmissionSubcategory(String emissionSubcategory) { this.emissionSubcategory = emissionSubcategory; }
    public BigDecimal getEnergyMeasurementValue() { return energyMeasurementValue; }
    public void setEnergyMeasurementValue(BigDecimal energyMeasurementValue) { this.energyMeasurementValue = energyMeasurementValue; }
    public BigDecimal getAdjustedEnergyValue() { return adjustedEnergyValue; }
    public void setAdjustedEnergyValue(BigDecimal adjustedEnergyValue) { this.adjustedEnergyValue = adjustedEnergyValue; }
    public BigDecimal getCarbonEmission() { return carbonEmission; }
    public void setCarbonEmission(BigDecimal carbonEmission) { this.carbonEmission = carbonEmission; }
    public String getMeasurementUnit() { return measurementUnit; }
    public void setMeasurementUnit(String measurementUnit) { this.measurementUnit = measurementUnit; }
    public Long getCollectionPointId() { return collectionPointId; }
    public void setCollectionPointId(Long collectionPointId) { this.collectionPointId = collectionPointId; }
    public Integer getCollectionPointType() { return collectionPointType; }
    public void setCollectionPointType(Integer collectionPointType) { this.collectionPointType = collectionPointType; }
    public String getEnergyAllocation() { return energyAllocation; }
    public void setEnergyAllocation(String energyAllocation) { this.energyAllocation = energyAllocation; }
    public String getFacilityName() { return facilityName; }
    public void setFacilityName(String facilityName) { this.facilityName = facilityName; }
    public Integer getStatus() { return status; }
    public void setStatus(Integer status) { this.status = status; }

    private BigDecimal adjustedCarbonEmission;
    public BigDecimal getAdjustedCarbonEmission() { return adjustedCarbonEmission; }
    public void setAdjustedCarbonEmission(BigDecimal value) { adjustedCarbonEmission = value; }
    private BigDecimal carbonEmissionFactor;
    public BigDecimal getCarbonEmissionFactor() { return carbonEmissionFactor; }
    public void setCarbonEmissionFactor(BigDecimal value) { carbonEmissionFactor = value; }
    private String carbonEmissionFactorUnit;
    public String getCarbonEmissionFactorUnit() { return carbonEmissionFactorUnit; }
    public void setCarbonEmissionFactorUnit(String value) { carbonEmissionFactorUnit = value; }
    private String carbonEmissionUnit;
    public String getCarbonEmissionUnit() { return carbonEmissionUnit; }
    public void setCarbonEmissionUnit(String value) { carbonEmissionUnit = value; }
    private Integer dataStatus;
    public Integer getDataStatus() { return dataStatus; }
    public void setDataStatus(Integer value) { dataStatus = value; }
    private String dataMissingDescription;
    public String getDataMissingDescription() { return dataMissingDescription; }
    public void setDataMissingDescription(String value) { dataMissingDescription = value; }
    private BigDecimal configuredFactor;
    public BigDecimal getConfiguredFactor() { return configuredFactor; }
    public void setConfiguredFactor(BigDecimal value) { configuredFactor = value; }
    private String configuredFactorUnit;
    public String getConfiguredFactorUnit() { return configuredFactorUnit; }
    public void setConfiguredFactorUnit(String value) { configuredFactorUnit = value; }
    private BigDecimal templateFactor;
    public BigDecimal getTemplateFactor() { return templateFactor; }
    public void setTemplateFactor(BigDecimal value) { templateFactor = value; }
    private String templateFactorUnit;
    public String getTemplateFactorUnit() { return templateFactorUnit; }
    public void setTemplateFactorUnit(String value) { templateFactorUnit = value; }
}
