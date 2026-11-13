package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.databind.JsonNode;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

/**
 * DQI 规则库版本查询响应 DTO（含维度规则列表）
 */
@Data
public class UncertaintyRulesetDto {

    /**
     * 规则库ID
     */
    private Long id;

    /**
     * 规则库版本号
     */
    private String rulesetVersion;

    /**
     * 生效日期
     */
    private LocalDate effectiveDate;

    /**
     * 规则库审核人
     */
    private String reviewer;

    /**
     * 按 param_type 的维度权重
     */
    private JsonNode dimensionWeights;

    /**
     * δ表实证标定信息
     */
    private JsonNode calibrationMeta;

    /**
     * SDQI→支撑半宽δ映射表
     */
    private JsonNode deltaTable;

    /**
     * Scope级 delta_cov_percent 封顶值（%）
     */
    private BigDecimal coverageDeltaCap;

    /**
     * Scope级单侧因子 ξ_cov 的 Beta 参数 α_cov
     */
    private BigDecimal coverageAlpha;

    /**
     * 本次升版变更理由
     */
    private String changeReason;

    /**
     * 创建人
     */
    private String createdBy;

    /**
     * 创建时间
     */
    private LocalDateTime createdAt;

    /**
     * 维度规则列表（listRulesets 时不填充）
     */
    private List<UncertaintyDimensionRuleDto> dimensions;
}
