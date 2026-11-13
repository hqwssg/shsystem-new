package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Scope 级完整性基准实体类（I6）
 * <p>
 * 对应表 uncertainty_scope_baseline，存储核算任务下每个 Scope
 * 的独立自上而下基准量，用于 Scope 级规模完整性判据。
 */
@Entity
@Table(name = "uncertainty_scope_baseline")
@Data
public class UncertaintyScopeBaseline {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 核算任务ID，逻辑关联 emission_calculation_template.id
     */
    @Column(name = "calculation_template_id", nullable = false)
    private Long calculationTemplateId;

    /**
     * Scope类别
     */
    @Column(name = "scope", nullable = false, length = 50)
    private String scope;

    /**
     * 独立自上而下基准量（必须为正；留空则该Scope走measured/disabled）
     */
    @Column(name = "benchmark_qty", columnDefinition = "DECIMAL(24,8)")
    private BigDecimal benchmarkQty;

    /**
     * 基准量单位（须与Scope内AD可比）
     */
    @Column(name = "benchmark_unit", length = 30)
    private String benchmarkUnit;

    /**
     * 基准来源：供电局结算单/设施台账/运量反算/上年清单等
     */
    @Column(name = "benchmark_source", length = 200)
    private String benchmarkSource;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    /**
     * 更新时间
     */
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }
}
