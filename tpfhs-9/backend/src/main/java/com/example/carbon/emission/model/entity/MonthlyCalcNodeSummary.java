package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 一个设计态核算节点在一个自然月、一个排放小类下的最新汇总。 */
@Entity
@Table(name = "emission_calc_node_summary_month",
        uniqueConstraints = @UniqueConstraint(name = "uk_node_month_subcategory",
                columnNames = {"template_id", "source_node_id", "year", "month", "emission_subcategory"}))
@Data
public class MonthlyCalcNodeSummary {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "template_id", nullable = false)
    private Long templateId;

    @Column(name = "source_node_id", nullable = false)
    private Long sourceNodeId;

    @Column(name = "parent_source_node_id")
    private Long parentSourceNodeId;

    @Column(name = "year", nullable = false)
    private Integer year;

    @Column(name = "month", nullable = false)
    private Integer month;

    @Column(name = "node_level", nullable = false)
    private Integer nodeLevel;

    @Column(name = "is_leaf_calc_node", nullable = false)
    private Integer isLeafCalcNode = 0;

    @Column(name = "emission_category", length = 100)
    private String emissionCategory;

    @Column(name = "emission_subcategory", nullable = false, length = 100)
    private String emissionSubcategory;

    @Column(name = "direct_energy_value", nullable = false, precision = 18, scale = 6)
    private BigDecimal directEnergyValue = BigDecimal.ZERO;

    @Column(name = "direct_carbon_emission", nullable = false, precision = 18, scale = 9)
    private BigDecimal directCarbonEmission = BigDecimal.ZERO;

    @Column(name = "subtotal_energy_value", nullable = false, precision = 18, scale = 6)
    private BigDecimal subtotalEnergyValue = BigDecimal.ZERO;

    @Column(name = "subtotal_carbon_emission", nullable = false, precision = 18, scale = 9)
    private BigDecimal subtotalCarbonEmission = BigDecimal.ZERO;

    @Column(name = "calculation_unit_code", length = 30)
    private String calculationUnitCode;

    @Column(name = "carbon_emission_factor", precision = 18, scale = 9)
    private BigDecimal carbonEmissionFactor;

    @Column(name = "summary_source", nullable = false)
    private Integer summarySource;

    @Column(name = "result_status", nullable = false)
    private Integer resultStatus = 1;

    @Column(name = "missing_collection_point_ids", length = 500)
    private String missingCollectionPointIds;

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
        if (isLeafCalcNode == null) isLeafCalcNode = 0;
        if (resultStatus == null) resultStatus = 1;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
