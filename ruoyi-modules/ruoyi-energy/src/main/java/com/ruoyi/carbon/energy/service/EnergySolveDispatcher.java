package com.ruoyi.carbon.energy.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.ruoyi.carbon.energy.cli.EnergyCliClient;

public final class EnergySolveDispatcher
{
    private static final Logger log = LoggerFactory.getLogger(EnergySolveDispatcher.class);

    private EnergySolveDispatcher()
    {
    }

    public static void dispatch(EnergyCliClient cli, String runId)
    {
        if (runId == null || runId.isBlank())
        {
            return;
        }
        try
        {
            cli.workerOnce(runId);
        }
        catch (Exception ex)
        {
            log.error("能量任务求解失败 runId={}: {}", runId, ex.getMessage());
        }
    }
}
