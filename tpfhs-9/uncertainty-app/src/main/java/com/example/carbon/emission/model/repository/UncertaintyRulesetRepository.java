package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

/**
 * DQI 规则库版本数据访问接口
 */
@Repository
public interface UncertaintyRulesetRepository extends JpaRepository<UncertaintyRuleset, Long> {

    /**
     * 根据规则库版本号查询
     *
     * @param rulesetVersion 规则库版本号
     * @return 规则库版本记录
     */
    Optional<UncertaintyRuleset> findByRulesetVersion(String rulesetVersion);

    /**
     * 判断规则库版本号是否已存在
     *
     * @param rulesetVersion 规则库版本号
     * @return 是否存在
     */
    boolean existsByRulesetVersion(String rulesetVersion);
}
