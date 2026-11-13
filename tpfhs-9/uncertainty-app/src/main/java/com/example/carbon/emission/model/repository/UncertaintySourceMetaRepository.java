package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * 不确定性分析排放源元信息数据访问接口
 */
@Repository
public interface UncertaintySourceMetaRepository extends JpaRepository<UncertaintySourceMeta, Long> {

    /**
     * 根据核算任务ID查询排放源元信息列表
     *
     * @param calculationTemplateId 核算任务ID
     * @return 排放源元信息列表
     */
    List<UncertaintySourceMeta> findByCalculationTemplateId(Long calculationTemplateId);

    /**
     * 根据核算任务ID+采集节点核算数据ID查询排放源元信息
     *
     * @param calculationTemplateId  核算任务ID
     * @param collectionNodeDataId 采集节点核算数据ID
     * @return 排放源元信息
     */
    Optional<UncertaintySourceMeta> findByCalculationTemplateIdAndCollectionNodeDataId(
            Long calculationTemplateId, Long collectionNodeDataId);
}
