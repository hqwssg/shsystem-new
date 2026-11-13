package com.example.carbon.emission.model.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 规则库启用维度集 DTO（按 param_type）
 * <p>
 * 返回某规则库版本下指定参数类型（AD/EF）的启用维度清单，以及归一化
 * 上下界：∑Qmin_w=Σw、∑Qmax_w=5Σw（仅 enabled=1 且 weight&gt;0 的维度参与求和）。
 */
@Data
public class UncertaintyDimensionSetDto {

    /**
     * 规则库版本号
     */
    private String rulesetVersion;

    /**
     * 参数类型：AD / EF
     */
    private String paramType;

    /**
     * 启用维度清单（enabled=1）
     */
    private List<DimItem> dimensions;

    /**
     * 归一化下界 ∑Qmin_w=Σw（仅 weight&gt;0 维度）
     */
    private BigDecimal sumQMinW;

    /**
     * 归一化上界 ∑Qmax_w=5Σw（仅 weight&gt;0 维度）
     */
    private BigDecimal sumQMaxW;

    /**
     * 启用维度条目
     */
    @Data
    public static class DimItem {

        /**
         * 维度编号：AD 用 A1/A2/A4/A5/A6，EF 用 E1-E6
         */
        private String dimCode;

        /**
         * 维度中文名称
         */
        private String dimName;

        /**
         * 维度权重
         */
        private BigDecimal weight;

        /**
         * 是否启用：1-是，0-否
         */
        private Integer enabled;
    }
}
