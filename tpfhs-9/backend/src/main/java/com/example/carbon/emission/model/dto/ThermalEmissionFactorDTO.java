package com.example.carbon.emission.model.dto;

import lombok.Data;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class ThermalEmissionFactorDTO {

    private Long id;

    private String emissionFactorName;

    @NotNull(message = "排放因子不能为空")
    @DecimalMin(value = "0", inclusive = true, message = "排放因子不能为负数")
    private BigDecimal emissionFactor;

    private String unit;

    private String source;

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
