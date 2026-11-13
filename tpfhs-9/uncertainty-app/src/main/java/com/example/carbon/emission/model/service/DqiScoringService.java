package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.DqiScoreSubmitRequest;
import com.example.carbon.emission.model.dto.DqiSuggestionDto;
import com.example.carbon.emission.model.dto.UncertaintyAuditDto;
import com.example.carbon.emission.model.dto.UncertaintySourceMetaUpdateRequest;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;

import java.util.List;

/**
 * DQI 自动评分引擎服务（M2a + I1 导入 + I2 人工复核提交 + O6 审计）
 * <p>
 * 评分算法严格实现技术规范 5.8.1 五步框架（V2.0 简化），
 * 软校验对应 5.8.4 的 W1-W3、W9-W13。
 */
public interface DqiScoringService {

    /**
     * 从核算结果快照导入排放源元信息（I1）
     * <p>
     * 对该核算任务每条采集节点核算数据生成一行排放源元信息；
     * 幂等：按 (calculation_template_id, collection_node_data_id) 已存在时仅
     * 更新名义值快照字段，不覆盖人工已补录的元信息字段（ad_* / ef_*）。
     *
     * @param calculationTemplateId 核算任务ID
     * @param calcYear              核算年度，为空时从核算任务周期结束日期年份推定
     * @return 导入/更新的排放源条数
     */
    int importSources(Long calculationTemplateId, Integer calcYear);

    /**
     * 人工补录/修改排放源元信息（A1-A6/E1-E6 驱动字段）
     * <p>
     * 仅更新请求中非 null 的字段。
     *
     * @param metaId  排放源元信息ID
     * @param request 元信息修改请求
     */
    void updateSourceMeta(Long metaId, UncertaintySourceMetaUpdateRequest request);

    /**
     * 查询核算任务下全部排放源元信息列表（I1 导入结果）
     *
     * @param calculationTemplateId 核算任务ID
     * @return 排放源元信息列表
     */
    List<UncertaintySourceMeta> listSources(Long calculationTemplateId);

    /**
     * 查询排放源的 DQI 评分记录
     *
     * @param sourceMetaId 排放源元信息ID
     * @param paramType    参数类型：AD / EF，为空时返回全部参数类型的评分
     * @return 评分记录列表
     */
    List<UncertaintyScore> getScores(Long sourceMetaId, String paramType);

    /**
     * M2a 五步算法生成/刷新建议分
     * <p>
     * 每条排放源对 AD 与 EF 各生成/更新一组 uncertainty_score 行
     * （按 (source_meta_id, param_type, dim_code) upsert，保留已有
     * final_score/reviewer 不覆盖）。
     *
     * @param calculationTemplateId 核算任务ID
     * @param rulesetVersion        规则库版本号
     * @param calcYear              核算年度，为空时从核算任务周期结束日期年份推定
     * @return 每排放源的维度评分结果与警告列表
     */
    List<DqiSuggestionDto> generateSuggestions(Long calculationTemplateId, String rulesetVersion, Integer calcYear);

    /**
     * I2 人工复核提交
     * <p>
     * 校验：final_score 必须 1-5 整数；维度键必须属于该 param_type 启用维度集；
     * score_source=manual_override 时 override_reason 必填；suggested_score=null
     * 的维度必须人工给 final；excluded 类的 A6 强制回写 3 分并标注
     * neutral_excluded。final_score 变化写审计；提交后 SDQI 较建议分状态
     * 变动≥0.5 时写入 W12 警告。
     *
     * @param sourceMetaId 排放源元信息ID
     * @param paramType    参数类型：AD / EF
     * @param request      提交请求
     * @param reviewer     复核人
     */
    void submitScores(Long sourceMetaId, String paramType, DqiScoreSubmitRequest request, String reviewer);

    /**
     * 审计链查询（O6，按时间倒序）
     *
     * @param sourceMetaId 排放源元信息ID
     * @return 审计记录列表
     */
    List<UncertaintyAuditDto> getAudit(Long sourceMetaId);
}
