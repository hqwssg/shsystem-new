package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class MonthlyPublicationCoordinatorTest {

    @Test
    void successfulPublicationReturnsPerTableCounts() {
        CalculationTemplateRepository tasks = mock(CalculationTemplateRepository.class);
        MonthlyCollectionDataService service = mock(MonthlyCollectionDataService.class);
        MonthlyStatisticsBuilder builder = mock(MonthlyStatisticsBuilder.class);
        MonthlyPublicationWriter writer = mock(MonthlyPublicationWriter.class);
        CalculationTemplate task = successfulTask();
        Template template = new Template(); template.setId(20L);
        when(tasks.findById(90L)).thenReturn(java.util.Optional.of(task));
        MonthlyCollectionDataService.PublicationBatch batch = new MonthlyCollectionDataService.PublicationBatch(
                java.util.List.of(java.time.YearMonth.of(2026, 1)), java.util.List.of(mockCandidate()));
        when(service.prepare(task, template, true)).thenReturn(batch);
        MonthlyPublicationPlan plan = new MonthlyPublicationPlan(20L, 100L, true,
                batch.months(), java.util.List.of(new com.example.carbon.emission.model.entity.MonthlyCollectionNodeData()),
                java.util.List.of(new com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary(),
                        new com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary()),
                java.util.List.of(new com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary()));
        when(builder.build(task, template, batch)).thenReturn(plan);

        MonthlyPublicationResult result = new MonthlyPublicationCoordinator(tasks, service, builder, writer)
                .publishSafely(task, template, true);

        assertThat(result.status()).isEqualTo("SUCCESS");
        assertThat(result.collectionRows()).isEqualTo(1);
        assertThat(result.nodeRows()).isEqualTo(2);
        assertThat(result.companyRows()).isEqualTo(1);
        verify(writer).replace(plan);
    }

    @Test
    void publicationFailureDoesNotChangeSuccessfulMainTask() {
        CalculationTemplateRepository tasks = mock(CalculationTemplateRepository.class);
        MonthlyCollectionDataService service = mock(MonthlyCollectionDataService.class);
        MonthlyStatisticsBuilder builder = mock(MonthlyStatisticsBuilder.class);
        MonthlyPublicationWriter writer = mock(MonthlyPublicationWriter.class);
        CalculationTemplate task = successfulTask();
        Template template = new Template(); template.setId(20L);
        when(tasks.findById(90L)).thenReturn(java.util.Optional.of(task));
        MonthlyCollectionDataService.PublicationBatch batch = new MonthlyCollectionDataService.PublicationBatch(
                java.util.List.of(java.time.YearMonth.of(2026, 1)), java.util.List.of(mockCandidate()));
        when(service.prepare(task, template, true)).thenReturn(batch);
        when(builder.build(task, template, batch)).thenThrow(new IllegalStateException("写入失败"));

        new MonthlyPublicationCoordinator(tasks, service, builder, writer)
                .publishSafely(task, template, true);

        assertThat(task.getStatus()).isEqualTo(CalculationTemplate.STATUS_SUCCESS);
        assertThat(task.getMonthlyRecordStatus()).isEqualTo("FAILED");
        assertThat(task.getMonthlyRecordMessage()).contains("写入失败");
    }

    @Test
    void optOutNeverTouchesMonthlyService() {
        CalculationTemplateRepository tasks = mock(CalculationTemplateRepository.class);
        MonthlyCollectionDataService service = mock(MonthlyCollectionDataService.class);
        MonthlyStatisticsBuilder builder = mock(MonthlyStatisticsBuilder.class);
        MonthlyPublicationWriter writer = mock(MonthlyPublicationWriter.class);
        CalculationTemplate task = successfulTask();

        new MonthlyPublicationCoordinator(tasks, service, builder, writer)
                .publishSafely(task, new Template(), false);

        assertThat(task.getMonthlyRecordStatus()).isEqualTo("NOT_REQUESTED");
        verifyNoInteractions(tasks, service, builder, writer);
    }

    @Test
    void persistedNonSuccessfulTaskNeverBuildsOrWritesMonthlyRows() {
        CalculationTemplateRepository tasks = mock(CalculationTemplateRepository.class);
        MonthlyCollectionDataService service = mock(MonthlyCollectionDataService.class);
        MonthlyStatisticsBuilder builder = mock(MonthlyStatisticsBuilder.class);
        MonthlyPublicationWriter writer = mock(MonthlyPublicationWriter.class);
        CalculationTemplate task = successfulTask();
        CalculationTemplate persisted = successfulTask(); persisted.setStatus(CalculationTemplate.STATUS_FAILED);
        when(tasks.findById(90L)).thenReturn(java.util.Optional.of(persisted));

        new MonthlyPublicationCoordinator(tasks, service, builder, writer)
                .publishSafely(task, new Template(), true);

        assertThat(task.getMonthlyRecordStatus()).isEqualTo("SKIPPED_NOT_SUCCESS");
        verifyNoInteractions(service, builder, writer);
    }

    private CalculationTemplate successfulTask() {
        CalculationTemplate task = new CalculationTemplate();
        task.setId(90L); task.setTemplateId(20L); task.setStatus(CalculationTemplate.STATUS_SUCCESS);
        return task;
    }

    private MonthlyCollectionDataService.CollectionCandidate mockCandidate() {
        com.example.carbon.emission.model.entity.CalculationNode node =
                new com.example.carbon.emission.model.entity.CalculationNode();
        com.example.carbon.emission.model.entity.CalculationNodeData source =
                new com.example.carbon.emission.model.entity.CalculationNodeData();
        com.example.carbon.emission.model.entity.MonthlyCollectionNodeData row =
                new com.example.carbon.emission.model.entity.MonthlyCollectionNodeData();
        return new MonthlyCollectionDataService.CollectionCandidate(node, source, row);
    }
}
