package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * DQI 规则库维度规则数据访问接口
 */
@Repository
public interface UncertaintyDimensionRuleRepository extends JpaRepository<UncertaintyDimensionRule, Long> {

    /**
     * 根据规则库ID查询全部维度规则
     *
     * @param rulesetId 规则库ID
     * @return 维度规则列表
     */
    List<UncertaintyDimensionRule> findByRulesetId(Long rulesetId);

    /**
     * 根据规则库ID+适用参数类型查询维度规则
     *
     * @param rulesetId 规则库ID
     * @param appliesTo 适用参数类型：AD / EF
     * @return 维度规则列表
     */
    List<UncertaintyDimensionRule> findByRulesetIdAndAppliesTo(Long rulesetId, String appliesTo);
}
