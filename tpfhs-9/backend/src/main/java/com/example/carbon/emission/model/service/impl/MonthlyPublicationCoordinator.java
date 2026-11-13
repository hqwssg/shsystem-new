package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import com.example.carbon.emission.model.service.EmissionDataFreshnessService;
import org.springframework.beans.factory.annotation.Autowired;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/** 把月度发布与主核算成功状态隔离。 */
@Service
public class MonthlyPublicationCoordinator {

    private static final Logger log = LoggerFactory.getLogger(MonthlyPublicationCoordinator.class);
    private final CalculationTemplateRepository tasks;
    private final MonthlyCollectionDataService collectionService;
    private final MonthlyStatisticsBuilder statisticsBuilder;
    private final MonthlyPublicationWriter writer;
    @Autowired
    private EmissionDataFreshnessService freshness;

    public MonthlyPublicationCoordinator(CalculationTemplateRepository tasks,
                                         MonthlyCollectionDataService collectionService,
                                         MonthlyStatisticsBuilder statisticsBuilder,
                                         MonthlyPublicationWriter writer) {
        this.tasks = tasks;
        this.collectionService = collectionService;
        this.statisticsBuilder = statisticsBuilder;
        this.writer = writer;
    }

    public MonthlyPublicationResult publishSafely(CalculationTemplate task, Template template, boolean requested) {
        return publish(task, template, requested, null);
    }

    MonthlyPublicationResult repair(CalculationTemplate task, Template template, MonthlyRepairContext context) {
        return publish(task, template, true, context);
    }

    private MonthlyPublicationResult publish(CalculationTemplate task, Template template, boolean requested,
                                             MonthlyRepairContext repair) {
        if (!requested) {
            if (task != null) {
                task.setMonthlyRecordStatus("NOT_REQUESTED");
                task.setMonthlyRecordMessage("本次未请求生成月度记录");
            }
            return new MonthlyPublicationResult("NOT_REQUESTED", 0, 0, 0, null);
        }
        if (task == null || template == null || task.getId() == null) {
            return new MonthlyPublicationResult("SKIPPED_INVALID", 0, 0, 0, "核算任务或模板为空");
        }
        if (repair == null && task.isReusedExistingResult()) {
            task.setMonthlyRecordStatus("SKIPPED_REUSED");
            task.setMonthlyRecordMessage("复用已有核算结果，本次未重复发布月度记录");
            return new MonthlyPublicationResult("SKIPPED_REUSED", 0, 0, 0, null);
        }
        try {
            CalculationTemplate persisted = tasks.findById(task.getId())
                    .orElseThrow(() -> new IllegalStateException("核算任务尚未持久化"));
            if (!Integer.valueOf(CalculationTemplate.STATUS_SUCCESS).equals(persisted.getStatus())) {
                task.setMonthlyRecordStatus("SKIPPED_NOT_SUCCESS");
                task.setMonthlyRecordMessage("核算任务未成功，不生成月度记录");
                return new MonthlyPublicationResult("SKIPPED_NOT_SUCCESS", 0, 0, 0, null);
            }
            if (repair != null && (!template.getId().equals(persisted.getTemplateId())
                    || !repair.month().atDay(1).equals(persisted.getCalculationCycleStartDate())
                    || !repair.month().atEndOfMonth().equals(persisted.getCalculationCycleEndDate())
                    || !java.util.Objects.equals(persisted.getDataRevision(), freshness.currentRevision(template.getId())))) {
                return new MonthlyPublicationResult("STALE", 0, 0, 0, "上月任务的数据版本已变化");
            }
            MonthlyCollectionDataService.PublicationBatch batch =
                    repair == null ? collectionService.prepare(task, template, true)
                            : collectionService.prepare(persisted, template, true, true);
            if (batch.months().isEmpty()) {
                task.setMonthlyRecordStatus("NO_COMPLETE_MONTH");
                task.setMonthlyRecordMessage("本次周期不生成月度记录");
                return new MonthlyPublicationResult("NO_COMPLETE_MONTH", 0, 0, 0, null);
            }
            if (batch.candidates().isEmpty()) {
                throw new IllegalStateException("成功核算任务没有可发布的采集点月度候选数据");
            }
            if (repair != null) {
                for (var candidate : batch.candidates()) {
                    var row = candidate.monthlyData();
                    if (repair.waitingPoints().contains(new MonthlyRepairContext.Point(
                            row.getCollectionPointType(), row.getCollectionPointId()))) {
                        row.setDataStatus(2);
                        row.setEnergyMeasurementValue(null);
                        row.setAdjustedEnergyValue(null);
                        row.setCarbonEmission(null);
                        row.setAdjustedCarbonEmission(null);
                    }
                }
            }
            MonthlyPublicationPlan plan = statisticsBuilder.build(task, template, batch);
            if (repair == null) {
                writer.replace(plan);
            } else {
                writer.repair(plan, repair);
            }
            task.setMonthlyRecordStatus("SUCCESS");
            task.setMonthlyRecordMessage("月度记录发布成功：采集点" + plan.collectionRows().size()
                    + "条，核算节点" + plan.nodeRows().size()
                    + "条，分公司" + plan.companyRows().size() + "条");
            return new MonthlyPublicationResult("SUCCESS", plan.collectionRows().size(),
                    plan.nodeRows().size(), plan.companyRows().size(), null);
        } catch (Exception error) {
            task.setMonthlyRecordStatus("FAILED");
            task.setMonthlyRecordMessage("月度记录生成失败：" + safeMessage(error));
            log.error("月度记录生成失败，原核算任务保持成功，模版ID: {}, 核算ID: {}",
                    task.getTemplateId(), task.getId(), error);
            return new MonthlyPublicationResult("FAILED", 0, 0, 0, safeMessage(error));
        }
    }

    private String safeMessage(Throwable error) {
        String message = error == null ? null : error.getMessage();
        return message == null || message.isBlank()
                ? (error == null ? "未知错误" : error.getClass().getSimpleName()) : message;
    }
}
