package com.example.carbon.emission.model.entity;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Scope 级完整性评估实体类（O7，每次运行每 Scope 一行）
 * <p>
 * 对应表 uncertainty_run_scope，存储一次模拟运行中每个 Scope
 * 的完整性判据（benchmark_measured/measured/disabled）、δ_cov 及
 * E[ξ_cov] 等评估结果。
 */
@Entity
@Table(name = "uncertainty_run_scope")
@Data
public class UncertaintyRunScope {

    /**
     * 主键ID
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 模拟运行ID，关联 uncertainty_run.id
     */
    @Column(name = "run_id", nullable = false)
    private Long runId;

    /**
     * Scope类别
     */
    @Column(name = "scope", nullable = false, length = 50)
    private String scope;

    /**
     * 该Scope记录级排放量小计E[g]
     */
    @Column(name = "scope_emission", columnDefinition = "DECIMAL(28,8)")
    private BigDecimal scopeEmission;

    /**
     * 判据类型：benchmark_measured/measured/disabled
     */
    @Column(name = "basis", nullable = false, length = 30)
    private String basis;

    /**
     * 独立基准量（无基准为NULL）
     */
    @Column(name = "benchmark_qty", columnDefinition = "DECIMAL(24,8)")
    private BigDecimal benchmarkQty;

    /**
     * 基准来源
     */
    @Column(name = "benchmark_source", length = 200)
    private String benchmarkSource;

    /**
     * 规模完整性：ΣAD_i/benchmark_qty
     */
    @Column(name = "r_benchmark", columnDefinition = "DECIMAL(10,6)")
    @JsonProperty("rBenchmark")
    private BigDecimal rBenchmark;

    /**
     * 排放量加权计量支撑度
     */
    @Column(name = "r_measured", columnDefinition = "DECIMAL(10,6)")
    @JsonProperty("rMeasured")
    private BigDecimal rMeasured;

    /**
     * 点数比x/n（仅诊断，不参与定价）
     */
    @Column(name = "point_ratio_xn", columnDefinition = "DECIMAL(10,6)")
    private BigDecimal pointRatioXn;

    /**
     * Scope级δ_cov（由r_eff直接查分段表，封顶coverage_delta_cap）
     */
    @Column(name = "delta_cov_percent", nullable = false,
            columnDefinition = "DECIMAL(6,3) NOT NULL DEFAULT 0")
    private BigDecimal deltaCovPercent = BigDecimal.ZERO;

    /**
     * E[ξ_cov]=1+(δ_cov/100)/16
     */
    @Column(name = "e_xi_cov", nullable = false,
            columnDefinition = "DECIMAL(10,6) NOT NULL DEFAULT 1")
    @JsonProperty("eXiCov")
    private BigDecimal eXiCov = BigDecimal.ONE;

    /**
     * basis=disabled时的强制披露文案
     */
    @Column(name = "disclosure", columnDefinition = "text")
    private String disclosure;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        if (deltaCovPercent == null) {
            deltaCovPercent = BigDecimal.ZERO;
        }
        if (eXiCov == null) {
            eXiCov = BigDecimal.ONE;
        }
    }
}
