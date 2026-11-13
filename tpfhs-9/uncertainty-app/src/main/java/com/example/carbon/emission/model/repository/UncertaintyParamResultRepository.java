package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyParamResult;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 参数级归一化与 Beta 分布参数数据访问接口
 */
@Repository
public interface UncertaintyParamResultRepository extends JpaRepository<UncertaintyParamResult, Long> {

    /**
     * 根据模拟运行ID查询参数级结果列表
     *
     * @param runId 模拟运行ID
     * @return 参数级结果列表
     */
    List<UncertaintyParamResult> findByRunId(Long runId);

    /**
     * 根据模拟运行ID+参数类型查询参数级结果列表
     *
     * @param runId     模拟运行ID
     * @param paramType 参数类型：AD / EF
     * @return 参数级结果列表
     */
    List<UncertaintyParamResult> findByRunIdAndParamType(Long runId, String paramType);
}
