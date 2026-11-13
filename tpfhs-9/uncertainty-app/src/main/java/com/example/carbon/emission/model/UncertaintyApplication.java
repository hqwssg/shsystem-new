package com.example.carbon.emission.model;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

/**
 * 碳排放不确定性分析模块独立应用
 * <p>
 * 与原 carbon-emission-model 工程共享同一 MySQL 数据库：
 * uncertainty_* 系列表由本工程读写，核算相关表（calculation_*、
 * emission_node 等）仅只读引用（importSources 数据来源）。
 * <p>
 * {@link EnableAsync} 支撑 MCS 大样本量（n≥100000）异步执行线程池
 * uncertaintyTaskExecutor。
 */
@EnableAsync
@SpringBootApplication
public class UncertaintyApplication {

    public static void main(String[] args) {
        SpringApplication.run(UncertaintyApplication.class, args);
    }
}
