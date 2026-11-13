package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 统计基准模板成功核算后形成的分公司月度能耗事实。 */
@Entity
@Table(name = "emission_company_energy_summary_month",
        uniqueConstraints = @UniqueConstraint(name = "uk_company_month_energy_subcategory",
                columnNames = {"company_dept_id", "year", "month", "energy_category_l1", "emission_subcategory"}))
@Data
public class MonthlyCompanyEnergySummary {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "company_dept_id", nullable = false)
    private Long companyDeptId;

    @Column(name = "year", nullable = false)
    private Integer year;

    @Column(name = "month", nullable = false)
    private Integer month;

    @Column(name = "energy_category_l1", nullable = false, length = 50)
    private String energyCategoryL1;

    @Column(name = "emission_category", length = 100)
    private String emissionCategory;

    @Column(name = "emission_subcategory", nullable = false, length = 100)
    private String emissionSubcategory;

    @Column(name = "standard_energy_value", nullable = false, precision = 18, scale = 6)
    private BigDecimal standardEnergyValue = BigDecimal.ZERO;

    @Column(name = "carbon_emission", nullable = false, precision = 18, scale = 9)
    private BigDecimal carbonEmission = BigDecimal.ZERO;

    @Column(name = "carbon_emission_factor", precision = 18, scale = 9)
    private BigDecimal carbonEmissionFactor;

    @Column(name = "calculation_unit_code", nullable = false, length = 30)
    private String calculationUnitCode;

    @Column(name = "result_status", nullable = false)
    private Integer resultStatus = 1;

    @Column(name = "ingest_status", nullable = false)
    private Integer ingestStatus = 0;

    @Column(name = "created_by")
    private Long createdBy;

    @Column(name = "updated_by")
    private Long updatedBy;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = createdAt;
        if (resultStatus == null) resultStatus = 1;
        if (ingestStatus == null) ingestStatus = 0;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
