package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyAudit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * DQI 评分变更审计数据访问接口
 */
@Repository
public interface UncertaintyAuditRepository extends JpaRepository<UncertaintyAudit, Long> {

    /**
     * 根据评分记录ID查询审计列表
     *
     * @param scoreId 评分记录ID
     * @return 审计列表
     */
    List<UncertaintyAudit> findByScoreId(Long scoreId);

    /**
     * 根据排放源元信息ID查询审计列表（按ID倒序，最新在前）
     *
     * @param sourceMetaId 排放源元信息ID
     * @return 审计列表
     */
    List<UncertaintyAudit> findBySourceMetaIdOrderByIdDesc(Long sourceMetaId);
}
