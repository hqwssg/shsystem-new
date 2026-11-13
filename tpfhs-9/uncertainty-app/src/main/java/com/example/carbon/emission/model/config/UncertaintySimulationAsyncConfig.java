package com.example.carbon.emission.model.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * 不确定性分析蒙特卡洛（MCS）异步执行线程池配置
 * <p>
 * 服务于大样本量（n≥阈值）的 MCS 运行：Web 端触发后立即返回 runId，
 * 由本线程池在后台完成参数化、完整性分量、抽样与统计落库，前端通过
 * 轮询运行状态获取结果。
 * <p>
 * 与 {@link AsyncThreadPoolConfig}（仅 job Profile、IO 密集核算调度）不同，
 * 本线程池不限定 Profile，Web 部署下始终可用，避免纯 Web 生产环境出现
 * 大 n 模拟阻塞请求线程。
 * <p>
 * 配置策略：
 * - 为操作系统预留 1 核，避免与 Tomcat、DB 驱动等争抢 CPU
 * - MCS 为 CPU 密集型（密集浮点抽样/统计），核心线程数取可用核数（非 ×2）
 * - 最大线程数 = 核心线程数：样本量计算可预期，不需要临时线程激增带来的抖动
 * - 队列容量 50：大 n 任务单次耗时较长，控制堆积量
 * - 拒绝策略 CallerRunsPolicy：队列与线程池均满时由提交线程执行，保证任务不丢失
 */
@Configuration
public class UncertaintySimulationAsyncConfig {

    /** 为操作系统预留的 CPU 核数 */
    private static final int OS_RESERVED_CORES = 1;

    /** 队列容量 */
    private static final int QUEUE_CAPACITY = 50;

    /**
     * 创建不确定性 MCS 异步执行线程池
     *
     * @return ThreadPoolTaskExecutor 实例（Bean 名 uncertaintyTaskExecutor）
     */
    @Bean(name = "uncertaintyTaskExecutor")
    public Executor uncertaintyTaskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();

        int cpuCount = Runtime.getRuntime().availableProcessors();
        // 可用核数 = 总核数 - 预留核（至少保留 1 核）
        int availableCores = Math.max(cpuCount - OS_RESERVED_CORES, 1);

        // CPU 密集型：核心线程数 = 可用核数
        executor.setCorePoolSize(availableCores);
        // 最大线程数 = 核心线程数：稳态场景不创建临时线程
        executor.setMaxPoolSize(availableCores);
        executor.setQueueCapacity(QUEUE_CAPACITY);

        executor.setKeepAliveSeconds(60);
        executor.setThreadNamePrefix("uncertainty-mcs-");

        // 队列与线程池均满时由提交线程执行，保证任务不丢失
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());

        // 关闭时等待在途 MCS 任务完成后退出
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(60);

        executor.initialize();
        return executor;
    }
}
