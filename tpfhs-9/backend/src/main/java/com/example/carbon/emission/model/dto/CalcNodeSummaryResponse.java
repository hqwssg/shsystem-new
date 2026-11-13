package com.example.carbon.emission.model.dto;

import com.example.carbon.emission.model.entity.CalcNodeSummary;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 核算汇总查询响应。
 *
 * <p>数据库继续保存稳定的小类编码；接口额外返回字典中文名称，供页面展示和
 * Excel 导出使用，避免把 PE_PF 等机器编码直接暴露给普通用户。</p>
 */
@Data
public class CalcNodeSummaryResponse {
    private Long id;
    private Long calculationTemplateId;
    private Long calculationNodeId;
    private Long sourceNodeId;
    private String sourceNodeName;
    private Long parentCalcNodeId;
    private Integer nodeLevel;
    private Integer isLeafCalcNode;
    private String energyCategoryL1;
    private String energyCategoryL1Name;
    private String energyCategoryL2;
    private String energyCategoryL2Name;
    private String energyCategoryL3;
    private String energyCategoryL3Name;
    private String emissionCategory;
    private String emissionCategoryName;
    private String emissionSubcategory;
    private String emissionSubcategoryName;
    private BigDecimal directEnergyValue;
    private BigDecimal directCarbonEmission;
    private BigDecimal subtotalEnergyValue;
    private BigDecimal childEnergyValue;
    private BigDecimal totalEnergyValue;
    private BigDecimal subtotalCarbonEmission;
    private BigDecimal childCarbonEmission;
    private BigDecimal totalCarbonEmission;
    /** 采集点原始计量单位快照，来自 emission_collection_node_data.measurement_unit。 */
    private String measurementUnit;
    private String calculationUnitCode;
    private BigDecimal carbonEmissionFactor;
    private Integer summarySource;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private Long createdBy;
    private Long updatedBy;

    public static CalcNodeSummaryResponse from(CalcNodeSummary source, String subcategoryName) {
        CalcNodeSummaryResponse target = new CalcNodeSummaryResponse();
        target.id = source.getId();
        target.calculationTemplateId = source.getCalculationTemplateId();
        target.calculationNodeId = source.getCalculationNodeId();
        target.sourceNodeId = source.getSourceNodeId();
        target.parentCalcNodeId = source.getParentCalcNodeId();
        target.nodeLevel = source.getNodeLevel();
        target.isLeafCalcNode = source.getIsLeafCalcNode();
        target.energyCategoryL1 = source.getEnergyCategoryL1();
        target.energyCategoryL2 = source.getEnergyCategoryL2();
        target.energyCategoryL3 = source.getEnergyCategoryL3();
        target.emissionCategory = source.getEmissionCategory();
        target.emissionSubcategory = source.getEmissionSubcategory();
        target.emissionSubcategoryName = subcategoryName;
        target.directEnergyValue = source.getDirectEnergyValue();
        target.directCarbonEmission = source.getDirectCarbonEmission();
        target.subtotalEnergyValue = source.getSubtotalEnergyValue();
        BigDecimal directEnergy = source.getDirectEnergyValue() == null ? BigDecimal.ZERO : source.getDirectEnergyValue();
        BigDecimal totalEnergy = source.getSubtotalEnergyValue() == null ? directEnergy : source.getSubtotalEnergyValue();
        target.childEnergyValue = totalEnergy.subtract(directEnergy);
        target.totalEnergyValue = totalEnergy;
        target.subtotalCarbonEmission = source.getSubtotalCarbonEmission();
        BigDecimal directCarbon = source.getDirectCarbonEmission() == null ? BigDecimal.ZERO : source.getDirectCarbonEmission();
        BigDecimal totalCarbon = source.getSubtotalCarbonEmission() == null ? directCarbon : source.getSubtotalCarbonEmission();
        target.childCarbonEmission = totalCarbon.subtract(directCarbon);
        target.totalCarbonEmission = totalCarbon;
        target.calculationUnitCode = source.getCalculationUnitCode();
        target.carbonEmissionFactor = source.getCarbonEmissionFactor();
        target.summarySource = source.getSummarySource();
        target.createdAt = source.getCreatedAt();
        target.updatedAt = source.getUpdatedAt();
        target.createdBy = source.getCreatedBy();
        target.updatedBy = source.getUpdatedBy();
        return target;
    }
}
