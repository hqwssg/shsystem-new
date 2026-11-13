package com.example.carbon.emission.model.dto;

import lombok.Data;

import java.util.List;

/**
 * M2a 单维度自动评分结果 DTO
 */
@Data
public class DqiDimSuggestionDto {

    /**
     * 参数类型：AD / EF
     */
    private String paramType;

    /**
     * 维度编号
     */
    private String dimCode;

    /**
     * M2a 建议分（缺失转人工时为 null）
     */
    private Integer suggested;

    /**
     * 判定依据（驱动字段取值+命中区间）
     */
    private String evidence;

    /**
     * 自动评分状态：complete / partial
     */
    private String status;

    /**
     * A6 来源标记：normal / neutral_excluded（仅 A6 维度有值）
     */
    private String a6Source;

    /**
     * ad_geo_basis 留空被默认填充标记
     */
    private Boolean defaultFilled;

    /**
     * 该维度触发的警告列表（编号+说明）
     */
    private List<String> warnings;
}
