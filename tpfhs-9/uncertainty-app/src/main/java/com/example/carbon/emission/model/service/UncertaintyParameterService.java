package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.ParamResultData;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;

import java.util.List;

/**
 * 不确定性参数化 Service（M3，规范 5.2/5.3）
 * <p>
 * 负责将单个排放源的单个参数（AD/EF）的 DQI 评分归一化为质量分数 x，
 * 查表4-4得 SDQI，再参数化为对称 Beta 分布（α=β=SDQI²）与支撑区间因子。
 */
public interface UncertaintyParameterService {

    /**
     * 参数化单个排放源的单个参数
     *
     * @param source    排放源元信息
     * @param scores    该排放源的全部维度评分（内部按 paramType 过滤）
     * @param ruleset   规则库版本（提供 δ 表）
     * @param dimRules  规则库维度规则（提供启用状态与权重）
     * @param paramType 参数类型：AD / EF
     * @return 参数化结果；任一参与维度 final_score 为空时 incomplete=true，调用方禁止运行模拟
     */
    ParamResultData parameterize(UncertaintySourceMeta source, List<UncertaintyScore> scores,
                                 UncertaintyRuleset ruleset, List<UncertaintyDimensionRule> dimRules,
                                 String paramType);
}
