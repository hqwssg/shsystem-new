package com.example.carbon.emission.model.dto;

import lombok.Data;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
public class WastewaterTreatmentFactorDTO {

    private Long id;

    private String emissionFactorName;

    private String wastewaterType;

    private BigDecimal od;

    private BigDecimal bo;

    private BigDecimal mcf;

    private BigDecimal gwp;

    @NotNull(message = "排放因子不能为空")
    @DecimalMin(value = "0", inclusive = true, message = "排放因子不能为负数")
    private BigDecimal emissionFactor;

    private String unit;

    private String source;

    private String description;

    private Long createdBy;

    private LocalDateTime createdAt;

    private Long updatedBy;

    private LocalDateTime updatedAt;
}
