package com.example.carbon.emission.model.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 不确定性分析蒙特卡洛模拟配置 DTO
 * <p>
 * 承载一次 MCS 运行的输入配置：迭代次数、置信水平、随机种子、
 * 完整性作用范围及规则库版本。空值由服务层填默认值。
 */
@Data
public class SimulationConfig {

    /**
     * MCS迭代次数（默认10000，范围1000-1000000，越界拒绝）
     */
    @JsonProperty("nIterations")
    private Integer nIterations;

    /**
     * 置信水平（默认0.95）
     */
    private BigDecimal confidenceLevel;

    /**
     * 随机种子（可空，空则由服务层生成并记录，固定可复现）
     */
    private Long randomSeed;

    /**
     * 完整性作用范围（默认scope，本期仅实现scope粒度，其他值拒绝）
     */
    private String completenessScopeLevel;

    /**
     * 规则库版本（可空，空则取最新版本）
     */
    private String rulesetVersion;
}
