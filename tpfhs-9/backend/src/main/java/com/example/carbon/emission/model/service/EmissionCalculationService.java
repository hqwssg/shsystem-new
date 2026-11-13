package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.entity.CalculationTemplate;

import java.time.LocalDate;

/**
 * 碳排放核算服务接口
 * 
 * 提供碳排放核算相关的计算功能。
 */
public interface EmissionCalculationService {

    /** 手动核算没有任何有效采集数据。 */
    int ERROR_CODE_NO_VALID_DATA = 3;

    /** 非累计采集点存在重复的有效计费周期。 */
    int ERROR_CODE_DUPLICATE_COLLECTION_PERIOD = 4;
    
    /**
     * 执行碳排放核算
     * 
     * 根据模板ID执行碳排放核算计算，遍历模板下的所有节点，
     * 采集数据并计算碳排放量。
     * 
     * @param templateId 模板ID
     */
    void executeEmissionCalculation(Long templateId);

    /**
     * 按指定周期执行一次手动核算，并记录手动发起人。
     * 周期边界由控制器校验为完整月份。
     */
    CalculationTemplate executeEmissionCalculation(Long templateId, LocalDate cycleStartDate,
                                                   LocalDate cycleEndDate, Long initiatorId,
                                                   String initiatorName);

    /** 按指定周期执行手动核算，并决定本次成功结果是否发布到月度表。 */
    CalculationTemplate executeEmissionCalculation(Long templateId, LocalDate cycleStartDate,
                                                   LocalDate cycleEndDate, Long initiatorId,
                                                   String initiatorName, boolean generateMonthlyRecords);
}
