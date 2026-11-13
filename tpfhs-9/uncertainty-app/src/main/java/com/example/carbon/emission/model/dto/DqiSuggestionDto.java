package com.example.carbon.emission.model.dto;

import lombok.Data;

import java.util.List;

/**
 * M2a 单排放源自动评分结果 DTO（AD 与 EF 两组维度合并返回）
 */
@Data
public class DqiSuggestionDto {

    /**
     * 排放源元信息ID
     */
    private Long sourceMetaId;

    /**
     * 排放源名称
     */
    private String sourceName;

    /**
     * 核算年度（用于 A5/E4 的 Δt 计算）
     */
    private Integer calcYear;

    /**
     * 规则库版本号
     */
    private String rulesetVersion;

    /**
     * 各维度自动评分结果
     */
    private List<DqiDimSuggestionDto> dimensions;

    /**
     * 该排放源级/任务级警告列表（如 W13）
     */
    private List<String> warnings;
}
