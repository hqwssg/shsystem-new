package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.UncertaintyRun;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 不确定性分析模拟运行数据访问接口
 */
@Repository
public interface UncertaintyRunRepository extends JpaRepository<UncertaintyRun, Long> {

    /**
     * 根据核算任务ID查询模拟运行列表（按ID倒序，最新在前）
     *
     * @param calculationTemplateId 核算任务ID
     * @return 模拟运行列表
     */
    List<UncertaintyRun> findByCalculationTemplateIdOrderByIdDesc(Long calculationTemplateId);
}
