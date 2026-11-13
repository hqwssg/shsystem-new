package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.databind.JsonNode;
import lombok.Data;

import java.math.BigDecimal;

/**
 * DQI 规则库维度规则 DTO
 * <p>
 * 新建规则库请求与规则库查询响应共用，entries/validRange 以 JsonNode 透出，
 * 与 uncertainty_dimension_rule 表 JSON 列一一对应。
 */
@Data
public class UncertaintyDimensionRuleDto {

    /**
     * 维度规则ID（响应时返回，新建时忽略）
     */
    private Long id;

    /**
     * 适用参数类型：AD / EF（单值）
     */
    private String appliesTo;

    /**
     * 维度编号：AD 用 A1/A2/A4/A5/A6，EF 用 E1-E6
     */
    private String dimCode;

    /**
     * 维度中文名称
     */
    private String dimName;

    /**
     * 是否启用：1-是，0-否
     */
    private Integer enabled;

    /**
     * 维度权重，须≥0
     */
    private BigDecimal weight;

    /**
     * 驱动字段名或派生量名
     */
    private String driver;

    /**
     * 规则类型：mapping / band / direct_score
     */
    private String ruleType;

    /**
     * mapping:{枚举值:分值}；band:[[下界(含),上界(不含),分值],...]；direct_score 为空对象
     */
    private JsonNode entries;

    /**
     * 缺失策略：to_manual / default_with_flag / neutral
     */
    private String nullPolicy;

    /**
     * 中性分值（null_policy=neutral 时必填）
     */
    private Integer neutralScore;

    /**
     * 触发中性分的枚举取值
     */
    private String neutralWhenValue;

    /**
     * 默认填充值（null_policy=default_with_flag 时必填）
     */
    private String defaultValue;

    /**
     * 默认填充时是否标注 default_filled=true：1-是，0-否
     */
    private Integer markDefaultFilled;

    /**
     * band 有效域 [下界,上界]
     */
    private JsonNode validRange;

    /**
     * 越域警告文本
     */
    private String outOfRangeWarning;
}
