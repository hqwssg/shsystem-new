package com.example.carbon.emission.model.dto;

import lombok.Data;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class ElectricityCarbonEmissionFactorDTO {
    
    private Long id;
    
    private String factorName;
    
    @NotNull(message = "碳排放因子值不能为空")
    @DecimalMin(value = "0", inclusive = true, message = "碳排放因子值不能为负数")
    private BigDecimal factorValue;
    
    private String unit;
    
    private String description;

    private String efSourceAuthority;
    private String efCompletenessScope;
    private String efDataRegion;
    private Integer efDataYear;
    private String efTechApplicability;
    private String efConversionChain;
    private Integer dqiE1Score;
    private Integer dqiE2Score;
    private Integer dqiE3Score;
    private Integer dqiE4Score;
    private Integer dqiE5Score;
    private Integer dqiE6Score;
    
    private Long createdBy;
    
    private LocalDateTime createdAt;
    
    private Long updatedBy;
    
    private LocalDateTime updatedAt;
}
