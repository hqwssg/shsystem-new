package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.service.EmissionCalculationService;
import com.example.carbon.emission.model.service.EmissionDataFreshnessService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.YearMonth;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class MonthlyRepairServiceTest {
    @Test
    @SuppressWarnings({"rawtypes", "unchecked"})
    void skipsUnregisteredTemplatesAndReusesCurrentSuccessfulJanuaryBoundaryTask() {
        var templates = mock(TemplateRepository.class);
        var nodes = mock(EmissionNodeRepository.class);
        var configs = mock(EmissionNodeConfigRepository.class);
        var inclusion = mock(NodeInclusionResolver.class);
        var summaries = mock(MonthlyCalcNodeSummaryRepository.class);
        var company = mock(MonthlyCompanyEnergySummaryRepository.class);
        var tasks = mock(CalculationTemplateRepository.class);
        var calculation = mock(EmissionCalculationService.class);
        var freshness = mock(EmissionDataFreshnessService.class);
        var publication = mock(MonthlyPublicationCoordinator.class);
        var baseline = mock(StatisticsBaselineTemplateService.class);
        var companies = mock(CompanyOwnershipService.class);
        var jdbc = mock(JdbcTemplate.class);
        var meter = mock(EnergyMeasurementCalculator.class);
        var factors = mock(FactorDimensionService.class);
        var repair = new MonthlyRepairService(templates, nodes, configs, inclusion, summaries, company,
                tasks, calculation, freshness, publication, baseline, companies, jdbc, meter, factors);

        var template = new Template(); template.setId(1L); template.setDeptId(3030L);
        var unregistered = new Template(); unregistered.setId(6L); unregistered.setDeptId(103L);
        var unassigned = new Template(); unassigned.setId(7L);
        var root = new EmissionNode(); root.setId(2L); root.setTypeId(1);
        var leaf = new EmissionNode(); leaf.setId(3L); leaf.setTypeId(3); leaf.setParentId(2L);
        var point = new EmissionNodeConfig(); point.setNodeId(3L); point.setCollectionPointType(1);
        point.setCollectionPointId(4L); point.setEmissionSubcategory("PE_PF");
        var task = new CalculationTemplate(); task.setId(5L); task.setStatus(CalculationTemplate.STATUS_SUCCESS);
        when(templates.findByEnabledTrueAndTemplateType(2)).thenReturn(List.of(unregistered, unassigned, template));
        when(companies.registeredId(103L)).thenReturn(null);
        when(companies.registeredId(null)).thenReturn(null);
        when(companies.registeredId(3030L)).thenReturn(3030L);
        when(nodes.findByTemplateId(1L)).thenReturn(List.of(root, leaf));
        when(inclusion.resolve(anyList())).thenReturn(Map.of(3L, new NodeInclusionResolver.InclusionDecision(true, null)));
        when(configs.findCollectionPointConfigsByTemplateId(1L)).thenReturn(List.of(point));
        when(factors.resolveSubcategoryCode("PE_PF")).thenReturn("PE_PF");
        when(freshness.currentRevision(1L)).thenReturn(7L);
        when(jdbc.query(anyString(), any(ResultSetExtractor.class), eq(4L))).thenAnswer(call -> {
            var result = mock(java.sql.ResultSet.class);
            when(result.next()).thenReturn(false);
            return ((ResultSetExtractor) call.getArgument(1)).extractData(result);
        });
        when(tasks.findFirstByTemplateIdAndCalculationCycleStartDateAndCalculationCycleEndDateAndDataRevisionOrderByIdDesc(
                1L, LocalDate.of(2025, 12, 1), LocalDate.of(2025, 12, 31), 7L)).thenReturn(Optional.of(task));

        repair.run(LocalDateTime.of(2026, 1, 25, 2, 0));
        repair.run(LocalDateTime.of(2026, 1, 26, 2, 0));

        var context = org.mockito.ArgumentCaptor.forClass(MonthlyRepairContext.class);
        verify(publication, times(2)).repair(eq(task), eq(template), context.capture());
        assertThat(context.getAllValues()).extracting(MonthlyRepairContext::pastDeadline).containsExactly(false, true);
        assertThat(context.getValue().month()).isEqualTo(YearMonth.of(2025, 12));
        assertThat(context.getValue().waitingPoints()).containsExactly(new MonthlyRepairContext.Point(1, 4));
        verify(nodes, never()).findByTemplateId(6L);
        verify(nodes, never()).findByTemplateId(7L);
        verifyNoInteractions(calculation);
    }
}
