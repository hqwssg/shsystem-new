package com.example.carbon.emission.model.dto;

import lombok.Data;

/**
 * I2 人工复核提交单维度评分项 DTO
 */
@Data
public class DqiScoreSubmitItem {

    /**
     * 维度编号（必须属于该 param_type 启用维度集）
     */
    private String dimCode;

    /**
     * 最终分（1-5 整数，必填）
     */
    private Integer finalScore;

    /**
     * 分值来源：auto / manual_override / expert_override；
     * 为空时按 finalScore 与建议分是否一致自动判定（一致 auto，不一致 manual_override）
     */
    private String scoreSource;

    /**
     * 人工覆盖理由（score_source=manual_override 时必填）
     */
    private String overrideReason;
}
