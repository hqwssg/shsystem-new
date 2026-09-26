package com.ruoyi.carbon.energy.service;

import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import java.util.concurrent.Executor;
import com.ruoyi.carbon.energy.cli.EnergyCliClient;
import com.ruoyi.carbon.energy.mapper.EnergyMapper;

@Component
public class EnergySolveRecovery implements ApplicationRunner
{
    private static final Logger log = LoggerFactory.getLogger(EnergySolveRecovery.class);

    private final EnergyCliClient cli;
    private final EnergyMapper mapper;
    private final Executor executor;

    public EnergySolveRecovery(EnergyCliClient cli, EnergyMapper mapper, @Qualifier("energyExecutor") Executor executor)
    {
        this.cli = cli;
        this.mapper = mapper;
        this.executor = executor;
    }

    @Override
    public void run(ApplicationArguments args)
    {
        try
        {
            cli.recoverExpired();
        }
        catch (Exception ex)
        {
            log.warn("回收过期能量任务失败: {}", ex.getMessage());
        }
        List<String> pending = mapper.selectPendingRunIds();
        if (pending == null || pending.isEmpty())
        {
            return;
        }
        for (String runId : pending)
        {
            executor.execute(() -> EnergySolveDispatcher.dispatch(cli, runId));
        }
    }
}
