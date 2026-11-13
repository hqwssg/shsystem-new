package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyScopeBaseline;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * Scope 级完整性基准数据访问接口
 */
@Repository
public interface UncertaintyScopeBaselineRepository extends JpaRepository<UncertaintyScopeBaseline, Long> {

    /**
     * 根据核算任务ID查询基准列表
     *
     * @param calculationTemplateId 核算任务ID
     * @return 基准列表
     */
    List<UncertaintyScopeBaseline> findByCalculationTemplateId(Long calculationTemplateId);

    /**
     * 根据核算任务ID+Scope类别查询基准
     *
     * @param calculationTemplateId 核算任务ID
     * @param scope                 Scope类别
     * @return 基准记录
     */
    Optional<UncertaintyScopeBaseline> findByCalculationTemplateIdAndScope(
            Long calculationTemplateId, String scope);
}
