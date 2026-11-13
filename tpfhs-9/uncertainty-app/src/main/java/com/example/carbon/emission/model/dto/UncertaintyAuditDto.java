package com.example.carbon.emission.model.dto;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * DQI 评分变更审计记录 DTO（O6）
 */
@Data
public class UncertaintyAuditDto {

    /**
     * 审计记录ID
     */
    private Long id;

    /**
     * 评分记录ID
     */
    private Long scoreId;

    /**
     * 排放源元信息ID
     */
    private Long sourceMetaId;

    /**
     * 参数类型：AD / EF
     */
    private String paramType;

    /**
     * 维度编号
     */
    private String dimCode;

    /**
     * 改前最终分（首次填写为 null）
     */
    private Integer oldScore;

    /**
     * 改后最终分
     */
    private Integer newScore;

    /**
     * 改前分值来源
     */
    private String oldSource;

    /**
     * 改后分值来源
     */
    private String newSource;

    /**
     * 覆盖理由
     */
    private String overrideReason;

    /**
     * 复核人
     */
    private String reviewer;

    /**
     * 复核时间
     */
    private LocalDateTime reviewTime;

    /**
     * 规则库版本
     */
    private String rulesetVersion;
}
