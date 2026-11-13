package com.example.carbon.emission.model.dto;

import lombok.Data;

/**
 * 排放源元信息人工补录/修改请求 DTO（I1）
 * <p>
 * 仅提交需要修改的字段，null 字段不覆盖现有值。
 */
@Data
public class UncertaintySourceMetaUpdateRequest {

    /**
     * A1驱动：online_meter/manual_ledger/statistical_report/literature_thirdparty/default_or_estimated
     */
    private String adMeteringTier;

    /**
     * A2驱动：calib_valid_cert/.../calib_not_applicable
     */
    private String adMeterCalibration;

    /**
     * A5驱动：AD数据年份
     */
    private Integer adDataYear;

    /**
     * A4驱动：direct_metered/ledger_complete/allocated/analogized/default_value
     */
    private String adGeoBasis;

    /**
     * A6驱动：数据采集质量1-5直接评分
     */
    private Integer adDataCollectionQuality;

    /**
     * E1驱动：official_national/national_standard/ipcc_default/authoritative_literature/general_or_estimated
     */
    private String efSourceAuthority;

    /**
     * E2驱动：full/minor_missing/partial_missing/major_only/unknown
     */
    private String efCompletenessScope;

    /**
     * E3驱动：in_boundary/same_grid/national/similar_economy/other_country
     */
    private String efDataRegion;

    /**
     * E4驱动：EF数据年份
     */
    private Integer efDataYear;

    /**
     * E5驱动：same_equipment_condition/railway_same_traction/railway_generic/adjacent_industry/generic_default
     */
    private String efTechApplicability;

    /**
     * E6驱动：direct_match/standard_single/multi_step/derived_from_other/unclear
     */
    private String efConversionChain;

    /**
     * 数据来源说明
     */
    private String dataSource;

    /**
     * 燃料/能源类型
     */
    private String energyType;
}
