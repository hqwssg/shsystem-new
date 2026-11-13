package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.UncertaintyDimensionSetDto;
import com.example.carbon.emission.model.dto.UncertaintyRulesetCreateRequest;
import com.example.carbon.emission.model.dto.UncertaintyRulesetDto;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;

import java.util.List;

/**
 * DQI 规则库服务
 * <p>
 * 负责不确定性分析（DQI+MCS）模块规则库版本的管理：内置默认规则库初始化、
 * 新版本创建（含规范 5.9 治理规则的阻断校验）、按版本查询与版本列表。
 */
public interface UncertaintyRulesetService {

    /**
     * 确保内置默认规则库存在
     * <p>
     * 若 uncertainty_ruleset 表为空，则创建内置默认规则库
     * （版本 DQI-RULES-2026.12）及规范 5.9 JSON 示例中的 11 个维度规则；
     * 否则直接返回已有规则库ID。
     *
     * @return 规则库ID
     */
    Long ensureDefaultRuleset();

    /**
     * 新建规则库版本
     * <p>
     * 创建前执行阻断校验：同版本号已存在、dimension_weights 存在权重&lt;0（W20）、
     * 某 param_type 启用维度数&lt;3、dim_code 在同一 param_type 内重复、
     * band 分段不连续/重叠/未覆盖 valid_range 全域、null_policy=neutral 但未配
     * neutral_when_value、applies_to 非 AD/EF 单值，任一失败抛
     * IllegalArgumentException 并定位。
     *
     * @param request 新建规则库请求
     * @return 新建规则库ID
     */
    Long createRuleset(UncertaintyRulesetCreateRequest request);

    /**
     * 按版本号查询规则库（含维度规则列表）
     *
     * @param version 规则库版本号
     * @return 规则库 DTO，entries 等 JSON 列反序列化为 JsonNode 透出
     */
    UncertaintyRulesetDto getRuleset(String version);

    /**
     * 查询全部规则库版本列表（不含维度规则明细）
     *
     * @return 规则库版本列表
     */
    List<UncertaintyRulesetDto> listRulesets();

    /**
     * 按版本号查询规则库实体
     * <p>
     * 供 Scope 完整性计算等需要规则库实体（coverage_delta_cap /
     * coverage_alpha 等字段）的调用方使用。
     *
     * @param version 规则库版本号
     * @return 规则库实体
     * @throws IllegalArgumentException 版本不存在
     */
    UncertaintyRuleset getRulesetEntity(String version);

    /**
     * 查询最新规则库实体（按 ID 最大者）
     *
     * @return 最新规则库实体
     * @throws IllegalStateException 规则库为空
     */
    UncertaintyRuleset getLatestRuleset();

    /**
     * 查询指定参数类型的启用维度集与归一化上下界
     * <p>
     * 返回该类型 enabled=1 的维度清单（dimCode/dimName/weight/enabled），
     * 以及 ∑Qmin_w=Σw、∑Qmax_w=5Σw（仅 weight&gt;0 维度参与求和）。
     *
     * @param version   规则库版本号
     * @param paramType 参数类型：AD / EF
     * @return 启用维度集
     * @throws IllegalArgumentException 版本不存在或 paramType 非 AD/EF
     */
    UncertaintyDimensionSetDto getDimensionSet(String version, String paramType);
}
