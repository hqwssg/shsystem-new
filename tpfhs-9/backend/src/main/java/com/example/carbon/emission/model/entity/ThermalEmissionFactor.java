package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;
import com.example.carbon.emission.model.support.DqiScoring;
import com.example.carbon.emission.model.support.EmissionFactorDqi;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 热力排放因子实体类
 * <p>
 * 用于存储热力排放因子数据，包括碳排放因子名称、因子值、单位、来源和说明。
 * 数据来源于《公共机构碳排放核算指南》等权威文件。
 * </p>
 */
@Entity
@Table(name = "emission_thermal_emission_factor")
@Data
public class ThermalEmissionFactor implements EmissionFactorDqi {

    /**
     * 主键ID，自增
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * 碳排放因子名称
     */
    @Column(name = "emission_factor_name", length = 200)
    private String emissionFactorName;

    /**
     * 碳排放因子值
     */
    @Column(name = "emission_factor", precision = 15, scale = 6)
    private BigDecimal emissionFactor;

    /**
     * 单位
     */
    @Column(name = "unit", length = 50)
    private String unit;

    /**
     * 数据来源
     */
    @Column(name = "source", length = 200)
    private String source;

    /**
     * 碳排放因子说明
     */
    @Column(name = "description", columnDefinition = "TEXT")
    private String description;

    @Column(name = "ef_source_authority", length = 40)
    private String efSourceAuthority;
    @Column(name = "ef_completeness_scope", length = 40)
    private String efCompletenessScope;
    @Column(name = "ef_data_region", length = 40)
    private String efDataRegion;
    @Column(name = "ef_data_year")
    private Integer efDataYear;
    @Column(name = "ef_tech_applicability", length = 40)
    private String efTechApplicability;
    @Column(name = "ef_conversion_chain", length = 40)
    private String efConversionChain;
    @Column(name = "dqi_e1_score")
    private Integer dqiE1Score;
    @Column(name = "dqi_e2_score")
    private Integer dqiE2Score;
    @Column(name = "dqi_e3_score")
    private Integer dqiE3Score;
    @Column(name = "dqi_e4_score")
    private Integer dqiE4Score;
    @Column(name = "dqi_e5_score")
    private Integer dqiE5Score;
    @Column(name = "dqi_e6_score")
    private Integer dqiE6Score;

    /**
     * 创建人ID
     */
    @Column(name = "created_by")
    private Long createdBy;

    /**
     * 创建时间
     */
    @Column(name = "created_at")
    private LocalDateTime createdAt;

    /**
     * 修改人ID
     */
    @Column(name = "updated_by")
    private Long updatedBy;

    /**
     * 修改时间
     */
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    /**
     * 实体持久化前自动设置创建时间和更新时间
     */
    @PrePersist
    protected void onCreate() {
        refreshDqiScores();
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }

    /**
     * 实体更新前自动设置更新时间
     */
    @PreUpdate
    protected void onUpdate() {
        refreshDqiScores();
        updatedAt = LocalDateTime.now();
    }

    private void refreshDqiScores() {
        dqiE1Score = DqiScoring.e1(efSourceAuthority);
        dqiE2Score = DqiScoring.e2(efCompletenessScope);
        dqiE3Score = DqiScoring.e3(efDataRegion);
        dqiE5Score = DqiScoring.e5(efTechApplicability);
        dqiE6Score = DqiScoring.e6(efConversionChain);
        if (!DqiScoring.isValidScore(dqiE4Score)) dqiE4Score = null;
    }
}
