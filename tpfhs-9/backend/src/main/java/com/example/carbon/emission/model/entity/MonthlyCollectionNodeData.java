package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/** 每个物理采集点当前最新的月度核算结果。 */
@Entity
@Table(name = "emission_collection_node_data_month",
        uniqueConstraints = @UniqueConstraint(name = "uk_collection_point_year_month",
                columnNames = {"collection_point_type", "collection_point_id", "year", "month"}))
@Data
public class MonthlyCollectionNodeData {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "year", nullable = false)
    private Integer year;

    @Column(name = "month", nullable = false)
    private Integer month;

    @Column(name = "collection_point_type", nullable = false)
    private Integer collectionPointType;

    @Column(name = "collection_point_id", nullable = false)
    private Long collectionPointId;

    @Column(name = "emission_category", length = 100)
    private String emissionCategory;

    @Column(name = "emission_subcategory", length = 100)
    private String emissionSubcategory;

    @Column(name = "carbon_emission_factor", precision = 15, scale = 6)
    private BigDecimal carbonEmissionFactor;

    @Column(name = "carbon_emission_factor_unit", length = 100)
    private String carbonEmissionFactorUnit;

    @Column(name = "carbon_emission_unit", length = 30)
    private String carbonEmissionUnit;

    @Column(name = "is_cumulative")
    private Integer isCumulative = 0;

    @Column(name = "is_mobile_source")
    private Integer isMobileSource = 0;

    @Column(name = "measurement_unit", length = 50)
    private String measurementUnit;

    @Column(name = "energy_category_l1", length = 50)
    private String energyCategoryL1;

    @Column(name = "energy_category_l2", length = 50)
    private String energyCategoryL2;

    @Column(name = "energy_category_l3", length = 50)
    private String energyCategoryL3;

    @Column(name = "energy_use_category", length = 100)
    private String energyUseCategory;

    @Column(name = "energy_measurement_value", precision = 18, scale = 6)
    private BigDecimal energyMeasurementValue;

    @Column(name = "carbon_emission", precision = 18, scale = 9)
    private BigDecimal carbonEmission;

    @Column(name = "adjusted_energy_value", precision = 18, scale = 6)
    private BigDecimal adjustedEnergyValue;

    @Column(name = "rollover_applied")
    private Boolean rolloverApplied = false;

    @Column(name = "rollover_threshold", precision = 18, scale = 6)
    private BigDecimal rolloverThreshold;

    @Column(name = "adjusted_carbon_emission", precision = 18, scale = 9)
    private BigDecimal adjustedCarbonEmission;

    @Column(name = "total_emission_calc_method")
    private Integer totalEmissionCalcMethod = 1;

    @Column(name = "collection_record_start_date")
    private LocalDate collectionRecordStartDate;

    @Column(name = "collection_record_end_date")
    private LocalDate collectionRecordEndDate;

    @Column(name = "data_status")
    private Integer dataStatus;

    @Column(name = "data_missing_description", length = 500)
    private String dataMissingDescription;

    @Column(name = "energy_attribution_dept_id")
    private Long energyAttributionDeptId;

    @Column(name = "energy_attribution_station_id")
    private Long energyAttributionStationId;

    @Column(name = "created_by")
    private Long createdBy;

    @Column(name = "updated_by")
    private Long updatedBy;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = createdAt;
        if (isCumulative == null) isCumulative = 0;
        if (isMobileSource == null) isMobileSource = 0;
        if (rolloverApplied == null) rolloverApplied = false;
        if (totalEmissionCalcMethod == null) totalEmissionCalcMethod = 1;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
