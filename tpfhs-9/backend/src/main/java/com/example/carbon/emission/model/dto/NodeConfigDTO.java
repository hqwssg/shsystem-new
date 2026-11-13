package com.example.carbon.emission.model.dto;

import lombok.Data;

import java.math.BigDecimal;

@Data
public class NodeConfigDTO {
    
    private Long nodeId;
    
    private Long updatedBy;
    
    private String emissionCategory;
    
    private String emissionSubcategory;
    
    private BigDecimal carbonEmissionFactor;

    /**
     * 碳排放因子单位（例如 tCO₂/MWh）。因子值和单位必须成对保存，
     * 否则无法确定采集活动量应换算到哪个分母单位。
     */
    private String carbonEmissionFactorUnit;
    
    private String carbonEmissionFactorDescription;

    private String carbonEmissionFactorSource;

    private Long carbonEmissionFactorId;

    private String carbonEmissionFactorName;

    /**
     * 仅当用户本次通过正式因子选择器重新选择时为 true。
     * 普通节点编辑不得借因子库后续变化刷新已冻结快照。
     */
    private Boolean carbonEmissionFactorReselected;

    private Integer carbonEmissionFactorDataYear;

    private Integer carbonEmissionFactorDqiE1Score;
    private Integer carbonEmissionFactorDqiE2Score;
    private Integer carbonEmissionFactorDqiE3Score;
    private Integer carbonEmissionFactorDqiE4Score;
    private Integer carbonEmissionFactorDqiE5Score;
    private Integer carbonEmissionFactorDqiE6Score;
    
    private String collectionDescription;
    
    private String equipmentCode;

    /**
     * 采集点类型：1-电力表，2-化石燃料，3-外购热能
     */
    private Integer collectionPointType;

    /**
     * 采集点ID，根据采集点类型指向对应采集点表的主键
     */
    private Long collectionPointId;
}
