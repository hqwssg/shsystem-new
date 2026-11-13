package com.example.carbon.emission.model.scheduler;

import com.example.carbon.emission.model.service.impl.MonthlyPredictionSender;
import com.example.carbon.emission.model.service.impl.MonthlyRepairService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.ZoneId;

@Component
@Profile("job")
public class MonthlyStatisticsScheduler {
    private final MonthlyRepairService repair;
    private final MonthlyPredictionSender sender;
    private final boolean repairEnabled;

    public MonthlyStatisticsScheduler(MonthlyRepairService repair, MonthlyPredictionSender sender,
            @Value("${carbon.statistics.monthly-repair.enabled:false}") boolean repairEnabled) {
        this.repair = repair;
        this.sender = sender;
        this.repairEnabled = repairEnabled;
    }

    @Scheduled(cron = "${carbon.statistics.monthly-repair.cron:0 0 2 * * *}", zone = MonthlyRepairService.ZONE)
    public void repairPreviousMonth() {
        if (repairEnabled) repair.run(LocalDateTime.now(ZoneId.of(MonthlyRepairService.ZONE)));
    }

    @Scheduled(fixedDelayString = "${carbon.statistics.prediction-send.delay-ms:60000}")
    public void sendCommittedSnapshots() {
        sender.drain();
    }
}
