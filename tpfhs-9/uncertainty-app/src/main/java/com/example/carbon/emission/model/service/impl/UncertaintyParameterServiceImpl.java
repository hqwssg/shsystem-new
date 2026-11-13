package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.ParamResultData;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.service.UncertaintyParameterService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 不确定性参数化 Service 实现（M3，规范 5.2/5.3）
 */
@Service
@Transactional(readOnly = true)
public class UncertaintyParameterServiceImpl implements UncertaintyParameterService {

    private static final Logger log = LoggerFactory.getLogger(UncertaintyParameterServiceImpl.class);

    /**
     * 数值计算统一保留小数位
     */
    private static final int SCALE = 6;

    /**
     * JSON 解析器（解析规则库 δ 表）
     */
    @Autowired
    private ObjectMapper objectMapper;

    @Override
    public ParamResultData parameterize(UncertaintySourceMeta source, List<UncertaintyScore> scores,
                                        UncertaintyRuleset ruleset, List<UncertaintyDimensionRule> dimRules,
                                        String paramType) {
        ParamResultData result = new ParamResultData();

        // 步骤1：按 dimCode 索引该排放源该参数类型的评分
        Map<String, UncertaintyScore> scoreByDim = new HashMap<>();
        if (scores != null) {
            for (UncertaintyScore score : scores) {
                if (paramType != null && paramType.equalsIgnoreCase(score.getParamType())) {
                    scoreByDim.put(score.getDimCode(), score);
                }
            }
        }

        // 步骤2：仅取 weight>0 且 enabled 的维度参与归一化（5.2：权重=0 等效禁用）
        BigDecimal sumQW = BigDecimal.ZERO;
        BigDecimal sumQMinW = BigDecimal.ZERO;
        BigDecimal sumQMaxW = BigDecimal.ZERO;
        boolean incomplete = false;
        if (dimRules != null) {
            for (UncertaintyDimensionRule rule : dimRules) {
                if (paramType == null || !paramType.equalsIgnoreCase(rule.getAppliesTo())) {
                    continue;
                }
                if (rule.getEnabled() == null || rule.getEnabled() != 1) {
                    continue;
                }
                BigDecimal weight = rule.getWeight();
                if (weight == null || weight.compareTo(BigDecimal.ZERO) <= 0) {
                    continue;
                }
                UncertaintyScore score = scoreByDim.get(rule.getDimCode());
                Integer effective = score == null ? null : (score.getFinalScore() != null
                        ? score.getFinalScore() : score.getSuggestedScore());
                // 任一参与维度 final_score 与 suggested_score 均为空 → 标记不完整
                // （DQI 自动评分已给出 suggested 但用户未手动确认的情况视为有效）
                if (effective == null) {
                    incomplete = true;
                    result.getWarnings().add("维度 " + rule.getDimCode()
                            + " 的 final_score 与 suggested_score 均为空，参数 " + paramType + " 评分不完整");
                    continue;
                }
                BigDecimal finalScore = BigDecimal.valueOf(effective);
                sumQW = sumQW.add(weight.multiply(finalScore));
                sumQMinW = sumQMinW.add(weight);
                sumQMaxW = sumQMaxW.add(weight.multiply(BigDecimal.valueOf(5)));
            }
        }
        result.setSumQW(sumQW.setScale(SCALE, RoundingMode.HALF_UP));
        result.setSumQMinW(sumQMinW.setScale(SCALE, RoundingMode.HALF_UP));
        result.setSumQMaxW(sumQMaxW.setScale(SCALE, RoundingMode.HALF_UP));

        // 无参与维度（归一化分母为0）同样视为不完整
        BigDecimal denominator = sumQMaxW.subtract(sumQMinW);
        if (denominator.compareTo(BigDecimal.ZERO) <= 0) {
            incomplete = true;
            result.getWarnings().add("参数 " + paramType + " 无 weight>0 且 enabled 的参与维度，无法归一化");
        }
        result.setIncomplete(incomplete);
        if (incomplete) {
            return result;
        }

        // 步骤3：公式(38) 归一化质量分数 x(%)，钳制在 [0,100]
        double x = denominator.compareTo(BigDecimal.ZERO) > 0
                ? sumQW.subtract(sumQMinW)
                        .divide(denominator, SCALE, RoundingMode.HALF_UP)
                        .multiply(BigDecimal.valueOf(100)).doubleValue()
                : 0.0;
        x = Math.max(0.0, Math.min(100.0, x));
        result.setXPercent(BigDecimal.valueOf(x).setScale(SCALE, RoundingMode.HALF_UP));

        // 步骤4：表4-4 等价式 SDQI=min(5.0, 1.0+0.5×floor(x/12.5))，x=100 → 5.0
        double sdqi = Math.min(5.0, 1.0 + 0.5 * Math.floor(x / 12.5));
        BigDecimal sdqiBd = BigDecimal.valueOf(sdqi).setScale(1, RoundingMode.HALF_UP);
        result.setSdqi(sdqiBd);

        // 步骤5：δ 查规则库 δ 表（key 为 SDQI 一位小数），α=β=SDQI²，支撑因子=1∓δ/100
        BigDecimal delta = lookupDelta(ruleset, sdqiBd);
        result.setDeltaPercent(delta.setScale(SCALE, RoundingMode.HALF_UP));
        BigDecimal sdqiSquare = sdqiBd.multiply(sdqiBd);
        result.setBetaAlpha(sdqiSquare.setScale(SCALE, RoundingMode.HALF_UP));
        result.setBetaBeta(sdqiSquare.setScale(SCALE, RoundingMode.HALF_UP));
        BigDecimal deltaFraction = delta.divide(BigDecimal.valueOf(100), SCALE, RoundingMode.HALF_UP);
        result.setSupportLowFactor(BigDecimal.ONE.subtract(deltaFraction).setScale(SCALE, RoundingMode.HALF_UP));
        result.setSupportHighFactor(BigDecimal.ONE.add(deltaFraction).setScale(SCALE, RoundingMode.HALF_UP));
        return result;
    }

    /**
     * 按 SDQI 查规则库 δ 表（JSON：{"5.0":5,"4.5":8,...}，key 为 SDQI 一位小数）
     */
    private BigDecimal lookupDelta(UncertaintyRuleset ruleset, BigDecimal sdqi) {
        String deltaTable = ruleset.getDeltaTable();
        if (deltaTable == null || deltaTable.isBlank()) {
            throw new IllegalStateException("规则库 " + ruleset.getRulesetVersion() + " 的δ表为空，无法参数化");
        }
        Map<String, BigDecimal> table;
        try {
            table = objectMapper.readValue(deltaTable, new TypeReference<Map<String, BigDecimal>>() {
            });
        } catch (Exception e) {
            throw new IllegalStateException("规则库 " + ruleset.getRulesetVersion() + " 的δ表JSON解析失败", e);
        }
        String key = String.format(Locale.ROOT, "%.1f", sdqi.doubleValue());
        BigDecimal delta = table.get(key);
        if (delta == null) {
            throw new IllegalStateException("规则库 " + ruleset.getRulesetVersion()
                    + " 的δ表缺少 SDQI=" + key + " 档位");
        }
        return delta;
    }
}
