package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.databind.JsonNode;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 新建 DQI 规则库版本请求 DTO
 */
@Data
public class UncertaintyRulesetCreateRequest {

    /**
     * 规则库版本号，如 DQI-RULES-2026.12
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
     * 本次升版变更理由
     */
    private String changeReason;

    /**
     * 创建人
     */
    private String createdBy;

    /**
     * 按 param_type 的维度权重：{"AD":{"A1":1.0,...},"EF":{"E1":1.0,...}}
     */
    private JsonNode dimensionWeights;

    /**
     * δ表实证标定信息（可选）
     */
    private JsonNode calibrationMeta;

    /**
     * SDQI→支撑半宽δ映射表
     */
    private JsonNode deltaTable;

    /**
     * Scope级 delta_cov_percent 封顶值（%），缺省 30
     */
    private BigDecimal coverageDeltaCap;

    /**
     * Scope级单侧因子 ξ_cov 的 Beta 参数 α_cov，缺省 15
     */
    private BigDecimal coverageAlpha;

    /**
     * 维度规则列表
     */
    private List<UncertaintyDimensionRuleDto> dimensions;
}
