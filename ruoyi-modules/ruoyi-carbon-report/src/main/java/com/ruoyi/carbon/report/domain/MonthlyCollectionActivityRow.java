package com.ruoyi.carbon.report.domain;

import java.math.BigDecimal;

/** One collection-point month used to expand report activity tables. */
public class MonthlyCollectionActivityRow
{
    private Integer collectionPointType;
    private Long collectionPointId;
    private Integer year;
    private Integer month;
    private String emissionCategory;
    private String emissionSubcategory;
    private String measurementUnit;
    private BigDecimal energyMeasurementValue;
    private BigDecimal adjustedEnergyValue;
    private BigDecimal carbonEmission;
    private BigDecimal adjustedCarbonEmission;
    private Integer dataStatus;

    public BigDecimal preferredEnergyValue()
    {
        return adjustedEnergyValue != null ? adjustedEnergyValue : energyMeasurementValue;
    }

    public BigDecimal preferredCarbonValue()
    {
        return adjustedEnergyValue != null ? adjustedCarbonEmission : carbonEmission;
    }

    public Integer getCollectionPointType() { return collectionPointType; }
    public void setCollectionPointType(Integer collectionPointType) { this.collectionPointType = collectionPointType; }
    public Long getCollectionPointId() { return collectionPointId; }
    public void setCollectionPointId(Long collectionPointId) { this.collectionPointId = collectionPointId; }
    public Integer getYear() { return year; }
    public void setYear(Integer year) { this.year = year; }
    public Integer getMonth() { return month; }
    public void setMonth(Integer month) { this.month = month; }
    public String getEmissionCategory() { return emissionCategory; }
    public void setEmissionCategory(String emissionCategory) { this.emissionCategory = emissionCategory; }
    public String getEmissionSubcategory() { return emissionSubcategory; }
    public void setEmissionSubcategory(String emissionSubcategory) { this.emissionSubcategory = emissionSubcategory; }
    public String getMeasurementUnit() { return measurementUnit; }
    public void setMeasurementUnit(String measurementUnit) { this.measurementUnit = measurementUnit; }
    public BigDecimal getEnergyMeasurementValue() { return energyMeasurementValue; }
    public void setEnergyMeasurementValue(BigDecimal energyMeasurementValue) { this.energyMeasurementValue = energyMeasurementValue; }
    public BigDecimal getAdjustedEnergyValue() { return adjustedEnergyValue; }
    public void setAdjustedEnergyValue(BigDecimal adjustedEnergyValue) { this.adjustedEnergyValue = adjustedEnergyValue; }
    public BigDecimal getCarbonEmission() { return carbonEmission; }
    public void setCarbonEmission(BigDecimal carbonEmission) { this.carbonEmission = carbonEmission; }
    public BigDecimal getAdjustedCarbonEmission() { return adjustedCarbonEmission; }
    public void setAdjustedCarbonEmission(BigDecimal adjustedCarbonEmission) { this.adjustedCarbonEmission = adjustedCarbonEmission; }
    public Integer getDataStatus() { return dataStatus; }
    public void setDataStatus(Integer dataStatus) { this.dataStatus = dataStatus; }
}
