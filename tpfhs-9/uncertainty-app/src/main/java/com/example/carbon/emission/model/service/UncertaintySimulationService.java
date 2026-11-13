package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.SimulationConfig;
import com.example.carbon.emission.model.dto.UncertaintyRunDetailDto;
import com.example.carbon.emission.model.entity.UncertaintyRun;

import java.util.List;

/**
 * 不确定性分析模拟运行 Service（M4 蒙特卡洛引擎 + M5 统计验证，规范 5.4/5.5/5.6）
 * <p>
 * 编排完整计算链：前置校验 → 创建运行记录 → M3 参数化落库 →
 * Scope 级完整性分量落库 → MCS 抽样 → M5 统计量与验证结论落库。
 */
public interface UncertaintySimulationService {

    /**
     * 执行一次蒙特卡洛模拟运行
     * <p>
     * 前置校验（配置、规则库、排放源、DQI 评分完整性）在本方法内同步完成，
     * 校验不通过立即抛出异常。校验通过后：
     * <ul>
     *   <li>nIterations ≥ 100000（大样本量）：以 RUNNING 状态落库运行记录后，
     *       提交专用线程池异步执行，本方法立即返回 runId；调用方通过
     *       {@link #getRunDetail(Long)} 或 {@link #listRuns(Long)} 轮询状态
     *       （RUNNING → SUCCESS/FAILED）。</li>
     *   <li>nIterations &lt; 100000（小样本量）：同步执行至完成后再返回 runId，
     *       执行异常时运行记录被标记为 FAILED 并写入 error_message 后重抛。</li>
     * </ul>
     *
     * @param calculationTemplateId 核算任务ID
     * @param config                模拟配置（空值字段由服务层填默认值）
     * @return 运行记录ID（uncertainty_run.id）
     * @throws IllegalArgumentException 配置非法（迭代次数越界/完整性作用范围非scope等）
     * @throws IllegalStateException    前置校验不满足（规则库缺失/存在未完成DQI评分/名义值非正等）
     * @throws RuntimeException         同步路径运行中异常；异常时运行记录会被标记为 FAILED 并写入 error_message 后重抛
     */
    Long run(Long calculationTemplateId, SimulationConfig config);

    /**
     * 查询核算任务下全部模拟运行列表（按ID倒序，最新在前）
     *
     * @param calculationTemplateId 核算任务ID
     * @return 模拟运行列表
     */
    List<UncertaintyRun> listRuns(Long calculationTemplateId);

    /**
     * 查询单次模拟运行的完整结果详情
     * <p>
     * 组装 O3/O4（运行记录的配置快照、统计量与验证结论）+
     * O7（Scope 级完整性评估）+ O1（参数级归一化与 Beta 分布参数）。
     *
     * @param runId 模拟运行ID
     * @return 运行结果详情
     * @throws IllegalArgumentException 运行记录不存在
     */
    UncertaintyRunDetailDto getRunDetail(Long runId);
}
