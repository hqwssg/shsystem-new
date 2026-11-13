package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyRunScope;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * Scope 级完整性评估数据访问接口
 */
@Repository
public interface UncertaintyRunScopeRepository extends JpaRepository<UncertaintyRunScope, Long> {

    /**
     * 根据模拟运行ID查询Scope级评估列表
     *
     * @param runId 模拟运行ID
     * @return Scope级评估列表
     */
    List<UncertaintyRunScope> findByRunId(Long runId);
}
