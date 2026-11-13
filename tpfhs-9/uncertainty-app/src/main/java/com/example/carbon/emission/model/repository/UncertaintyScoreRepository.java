package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyScore;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

/**
 * DQI 评分数据访问接口
 */
@Repository
public interface UncertaintyScoreRepository extends JpaRepository<UncertaintyScore, Long> {

    /**
     * 根据排放源元信息ID查询评分列表
     *
     * @param sourceMetaId 排放源元信息ID
     * @return 评分列表
     */
    List<UncertaintyScore> findBySourceMetaId(Long sourceMetaId);

    /**
     * 根据排放源元信息ID集合批量查询评分列表
     *
     * @param sourceMetaIds 排放源元信息ID集合
     * @return 评分列表
     */
    List<UncertaintyScore> findBySourceMetaIdIn(Collection<Long> sourceMetaIds);

    /**
     * 根据排放源元信息ID+参数类型+维度编号查询评分
     *
     * @param sourceMetaId 排放源元信息ID
     * @param paramType    参数类型：AD / EF
     * @param dimCode      维度编号
     * @return 评分记录
     */
    Optional<UncertaintyScore> findBySourceMetaIdAndParamTypeAndDimCode(
            Long sourceMetaId, String paramType, String dimCode);
}
