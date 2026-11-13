package com.example.carbon.emission.model.config;

import javax.sql.DataSource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.Resource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.stereotype.Component;

/** Restores the idempotent statistics and GoView demo dataset after startup. */
@Component
@ConditionalOnProperty(name = "carbon.statistics.demo.enabled", havingValue = "true", matchIfMissing = true)
public class StatisticsDemoDataInitializer implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(StatisticsDemoDataInitializer.class);
    private static final Resource DEMO_DATA = new ClassPathResource("demo-data/carbon_statistics_demo.sql");

    private final DataSource dataSource;

    public StatisticsDemoDataInitializer(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public void run(ApplicationArguments args) {
        ResourceDatabasePopulator populator = new ResourceDatabasePopulator();
        populator.setSqlScriptEncoding("UTF-8");
        populator.addScript(DEMO_DATA);
        populator.execute(dataSource);
        log.info("Statistics and GoView demo dataset is ready");
    }
}
