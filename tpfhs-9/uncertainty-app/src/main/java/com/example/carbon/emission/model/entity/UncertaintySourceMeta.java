package com.example.carbon.emission.model.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 不确定性分析排放源元信息实体类（I1）
 * <p>
 * 对应表 uncertainty_source_meta，快照自核算结果并支持人工补录，
 * 存储每个排放源的 AD/EF 名义值及各评分维度驱动字段取值。
 */
@Entity
@Table(name = "uncertainty_source_meta")
@Data
public class UncertaintySourceMeta {

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
     * 采集节点核算数据ID，逻辑回溯 emission_collection_node_data.id
     */
    @Column(name = "collection_node_data_id")
    private Long collectionNodeDataId;

    /**
     * 源节点ID，逻辑回溯 emission_node.id
     */
    @Column(name = "source_node_id")
    private Long sourceNodeId;

    /**
     * 排放源名称
     */
    @Column(name = "source_name", nullable = false, length = 200)
    private String sourceName;

    /**
     * Scope类别（emission_category：scope1/scope2/scope3等）
     */
    @Column(name = "scope", length = 50)
    private String scope;

    /**
     * 排放数据小类（emission_subcategory）
     */
    @Column(name = "emission_subcategory", length = 100)
    private String emissionSubcategory;

    /**
     * 燃料/能源类型
     */
    @Column(name = "energy_type", length = 50)
    private String energyType;

    /**
     * 活动数据AD名义值（核算单位能耗值）
     */
    @Column(name = "ad_value", columnDefinition = "DECIMAL(24,8)")
    private BigDecimal adValue;

    /**
     * AD单位（unit_code）
     */
    @Column(name = "ad_unit", length = 30)
    private String adUnit;

    /**
     * 排放因子EF名义值
     */
    @Column(name = "ef_value", columnDefinition = "DECIMAL(24,12)")
    private BigDecimal efValue;

    /**
     * EF单位
     */
    @Column(name = "ef_unit", length = 30)
    private String efUnit;

    /**
     * 排放量E=AD×EF（tCO2）
     */
    @Column(name = "emission_value", columnDefinition = "DECIMAL(24,8)")
    private BigDecimal emissionValue;

    /**
     * 数据来源说明
     */
    @Column(name = "data_source", length = 500)
    private String dataSource;

    /**
     * A1驱动：online_meter/manual_ledger/statistical_report/literature_thirdparty/default_or_estimated
     */
    @Column(name = "ad_metering_tier", length = 40)
    private String adMeteringTier;

    /**
     * A2驱动：calib_valid_cert/.../calib_not_applicable
     */
    @Column(name = "ad_meter_calibration", length = 40)
    private String adMeterCalibration;

    /**
     * A5驱动：AD数据年份
     */
    @Column(name = "ad_data_year")
    private Integer adDataYear;

    /**
     * A4驱动：direct_metered/ledger_complete/allocated/analogized/default_value
     */
    @Column(name = "ad_geo_basis", length = 40)
    private String adGeoBasis;

    /**
     * A6驱动：数据采集质量1-5直接评分（excluded类自动中性3分）
     */
    @Column(name = "ad_data_collection_quality")
    private Integer adDataCollectionQuality;

    /**
     * E1驱动：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated
     */
    @Column(name = "ef_source_authority", length = 40)
    private String efSourceAuthority;

    /**
     * E2驱动：full/minor_missing/partial_missing/major_only/unknown
     */
    @Column(name = "ef_completeness_scope", length = 40)
    private String efCompletenessScope;

    /**
     * E3驱动：in_boundary/same_grid/national/similar_economy/other_country
     */
    @Column(name = "ef_data_region", length = 40)
    private String efDataRegion;

    /**
     * E4驱动：EF数据年份
     */
    @Column(name = "ef_data_year")
    private Integer efDataYear;

    /**
     * E5驱动：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default
     */
    @Column(name = "ef_tech_applicability", length = 40)
    private String efTechApplicability;

    /**
     * E6驱动：direct_match/standard_single/multi_step/derived_from_other/unclear
     */
    @Column(name = "ef_conversion_chain", length = 40)
    private String efConversionChain;

    /**
     * A3废弃字段检测警告（导入不阻断）
     */
    @Column(name = "deprecated_fields_warning", length = 1000)
    private String deprecatedFieldsWarning;

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
