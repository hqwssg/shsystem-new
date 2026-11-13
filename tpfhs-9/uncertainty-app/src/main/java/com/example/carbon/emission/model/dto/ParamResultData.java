package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 参数级归一化与 Beta 分布参数化结果 DTO（规范 5.2/5.3）
 * <p>
 * 承载单个参数（AD/EF）的加权总分、归一化边界、质量分数 x、
 * SDQI、Beta 形状参数（α=β=SDQI²）、支撑半宽 δ 与支撑区间因子。
 */
@Data
public class ParamResultData {

    /**
     * 加权总分∑Q_w=Σ(w_j×s_j)
     */
    private BigDecimal sumQW;

    /**
     * 归一化下界∑Qmin_w=Σw_j
     */
    private BigDecimal sumQMinW;

    /**
     * 归一化上界∑Qmax_w=5×Σw_j
     */
    private BigDecimal sumQMaxW;

    /**
     * 归一化质量分数x(%)
     */
    @JsonProperty("xPercent")
    private BigDecimal xPercent;

    /**
     * SDQI（表4-4，1.0-5.0步进0.5）
     */
    private BigDecimal sdqi;

    /**
     * Beta分布形状参数α=SDQI²
     */
    private BigDecimal betaAlpha;

    /**
     * Beta分布形状参数β=SDQI²
     */
    private BigDecimal betaBeta;

    /**
     * 支撑半宽δ（SDQI查δ表，名义值%）
     */
    private BigDecimal deltaPercent;

    /**
     * 支撑区间下因子1-δ/100
     */
    private BigDecimal supportLowFactor;

    /**
     * 支撑区间上因子1+δ/100
     */
    private BigDecimal supportHighFactor;

    /**
     * 评分不完整标记：任一参与维度final_score为空（或无参与维度）时为true，
     * 调用方禁止运行模拟
     */
    private boolean incomplete;

    /**
     * 本参数触发的警告
     */
    private List<String> warnings = new ArrayList<>();
}
