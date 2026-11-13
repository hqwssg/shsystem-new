package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.CalcUnitDefaultRepository;
import com.example.carbon.emission.model.repository.CalculationNodeRepository;
import com.example.carbon.emission.model.repository.DataDictItemRepository;
import com.example.carbon.emission.model.service.UnitConversionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.YearMonth;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MonthlyStatisticsBuilderTest {

    @Mock CalculationNodeRepository calculationNodes;
    @Mock UnitConversionService conversions;
    @Mock FactorDimensionService factors;
    @Mock CalcUnitDefaultRepository unitDefaults;
    @Mock DataDictItemRepository dictItems;
    @Mock StatisticsBaselineTemplateService baselines;
    MonthlyStatisticsBuilder builder;

    @BeforeEach
    void setUp() {
        builder = new MonthlyStatisticsBuilder(calculationNodes, conversions, factors,
                unitDefaults, dictItems, baselines);
        when(factors.resolveSubcategoryCode(anyString())).thenReturn("PE_PF");
        when(conversions.convertToCalculationUnitRequired(eq("PE_PF"), eq("MWh"), any(BigDecimal.class)))
                .thenAnswer(call -> call.getArgument(2));
        lenient().when(conversions.convertRequired(eq("PE_PF"), eq("MWh"), eq("MWh"), any(BigDecimal.class)))
                .thenAnswer(call -> call.getArgument(3));
        CalcUnitDefault defaults = new CalcUnitDefault();
        defaults.setSubcategoryCode("PE_PF"); defaults.setCalculationUnit("MWh"); defaults.setReportUnit("MWh");
        when(unitDefaults.findBySubcategoryCode("PE_PF")).thenReturn(Optional.of(defaults));
        DataDictItem item = new DataDictItem(); item.setParentCode("PE");
        when(dictItems.findByItemCode("PE_PF")).thenReturn(Optional.of(item));
    }

    @ParameterizedTest
    @ValueSource(ints = {2, 3, 4, 5})
    void propagatesEveryAbnormalStatusToAncestorsButKeepsMissingIdsDirectOnly(int dataStatus) {
        CalculationNode root = node(1L, 10L, 1, null);
        CalculationNode calc = node(2L, 20L, 2, 1L);
        CalculationNode abnormalPoint = node(3L, 30L, 3, 2L);
        CalculationNode normalPoint = node(4L, 40L, 3, 1L);
        when(calculationNodes.findByCalculationTemplateId(90L))
                .thenReturn(List.of(root, calc, abnormalPoint, normalPoint));
        when(baselines.isBaseline(100L, 200L)).thenReturn(true);

        MonthlyCollectionDataService.PublicationBatch batch = new MonthlyCollectionDataService.PublicationBatch(
                List.of(YearMonth.of(2026, 1)), List.of(
                candidate(abnormalPoint, 10, 5, dataStatus), candidate(normalPoint, 5, 2, 1)));
        MonthlyPublicationPlan plan = builder.build(task(), template(), batch);

        assertThat(plan.nodeRows()).hasSize(2);
        MonthlyCalcNodeSummary calcRow = plan.nodeRows().stream()
                .filter(row -> row.getSourceNodeId().equals(20L)).findFirst().orElseThrow();
        MonthlyCalcNodeSummary rootRow = plan.nodeRows().stream()
                .filter(row -> row.getSourceNodeId().equals(10L)).findFirst().orElseThrow();
        assertThat(calcRow.getResultStatus()).isEqualTo(2);
        assertThat(calcRow.getMissingCollectionPointIds()).isEqualTo("30");
        assertThat(rootRow.getResultStatus()).isEqualTo(2);
        assertThat(rootRow.getMissingCollectionPointIds()).isNull();
        assertThat(rootRow.getDirectEnergyValue()).isEqualByComparingTo("5.000000");
        assertThat(rootRow.getSubtotalEnergyValue()).isEqualByComparingTo("15.000000");
        assertThat(rootRow.getSummarySource()).isEqualTo(3);

        assertThat(plan.companyRows()).hasSize(1);
        MonthlyCompanyEnergySummary company = plan.companyRows().get(0);
        assertThat(company.getStandardEnergyValue()).isEqualByComparingTo("15.000000");
        assertThat(company.getCarbonEmission()).isEqualByComparingTo("7.000000000");
        assertThat(company.getResultStatus()).isEqualTo(2);
        assertThat(company.getIngestStatus()).isZero();
    }

    @Test
    void sortsDirectMissingIdsAndExcludesNestedCollectionPoints() {
        CalculationNode root = node(1L, 10L, 1, null);
        CalculationNode parent = node(2L, 20L, 2, 1L);
        CalculationNode nested = node(3L, 21L, 2, 2L);
        CalculationNode directLater = node(4L, 31L, 3, 2L);
        CalculationNode nestedPoint = node(5L, 25L, 3, 3L);
        CalculationNode directEarlier = node(6L, 30L, 3, 2L);
        when(calculationNodes.findByCalculationTemplateId(90L)).thenReturn(List.of(
                root, parent, nested, directLater, nestedPoint, directEarlier));
        when(baselines.isBaseline(100L, 200L)).thenReturn(false);
        MonthlyCollectionDataService.PublicationBatch batch = new MonthlyCollectionDataService.PublicationBatch(
                List.of(YearMonth.of(2026, 1)), List.of(
                candidate(directLater, 1, 1, 2),
                candidate(nestedPoint, 1, 1, 3),
                candidate(directEarlier, 1, 1, 4)));

        MonthlyPublicationPlan plan = builder.build(task(), template(), batch);

        MonthlyCalcNodeSummary parentRow = plan.nodeRows().stream()
                .filter(row -> row.getSourceNodeId().equals(20L)).findFirst().orElseThrow();
        MonthlyCalcNodeSummary nestedRow = plan.nodeRows().stream()
                .filter(row -> row.getSourceNodeId().equals(21L)).findFirst().orElseThrow();
        MonthlyCalcNodeSummary rootRow = plan.nodeRows().stream()
                .filter(row -> row.getSourceNodeId().equals(10L)).findFirst().orElseThrow();
        assertThat(parentRow.getMissingCollectionPointIds()).isEqualTo("30,31");
        assertThat(nestedRow.getMissingCollectionPointIds()).isEqualTo("25");
        assertThat(rootRow.getMissingCollectionPointIds()).isNull();
        assertThat(plan.nodeRows()).allMatch(row -> row.getResultStatus() == 2);
    }

    @Test
    void keepsNodeStatusConsistentAcrossSubcategoriesAndGroupsCompanyDimensions() {
        CalculationNode root = node(1L, 10L, 1, null);
        CalculationNode electricity = node(2L, 30L, 3, 1L);
        CalculationNode heat = node(3L, 40L, 3, 1L);
        when(calculationNodes.findByCalculationTemplateId(90L))
                .thenReturn(List.of(root, electricity, heat));
        when(baselines.isBaseline(100L, 200L)).thenReturn(true);
        configureCategory("SE_HEAT", "GJ", "SE");
        MonthlyCollectionDataService.PublicationBatch batch = new MonthlyCollectionDataService.PublicationBatch(
                List.of(YearMonth.of(2026, 1)), List.of(
                candidate(electricity, 10, 5, 2, "PE_PF", "electricity", "MWh"),
                candidate(heat, 4, 2, 1, "SE_HEAT", "heat", "GJ")));

        MonthlyPublicationPlan plan = builder.build(task(), template(), batch);

        assertThat(plan.nodeRows()).hasSize(2)
                .extracting(MonthlyCalcNodeSummary::getResultStatus)
                .containsOnly(2);
        assertThat(plan.companyRows()).hasSize(2)
                .extracting(MonthlyCompanyEnergySummary::getResultStatus)
                .containsOnly(2);
        assertThat(plan.companyRows()).extracting(MonthlyCompanyEnergySummary::getEnergyCategoryL1)
                .containsExactlyInAnyOrder("electricity", "heat");
        assertThat(plan.companyRows()).extracting(MonthlyCompanyEnergySummary::getEmissionSubcategory)
                .containsExactlyInAnyOrder("PE_PF", "SE_HEAT");
        assertThat(plan.companyRows()).allMatch(row -> row.getIngestStatus() == 0);
    }

    @Test
    void ordinaryTemplateDoesNotCreateCompanyRows() {
        CalculationNode root = node(1L, 10L, 1, null);
        CalculationNode point = node(2L, 30L, 3, 1L);
        when(calculationNodes.findByCalculationTemplateId(90L)).thenReturn(List.of(root, point));
        when(baselines.isBaseline(100L, 200L)).thenReturn(false);
        MonthlyCollectionDataService.PublicationBatch batch = new MonthlyCollectionDataService.PublicationBatch(
                List.of(YearMonth.of(2026, 1)), List.of(candidate(point, 10, 5, 1)));

        MonthlyPublicationPlan plan = builder.build(task(), template(), batch);

        assertThat(plan.collectionRows()).hasSize(1);
        assertThat(plan.nodeRows()).hasSize(1);
        assertThat(plan.companyRows()).isEmpty();
    }

    private CalculationTemplate task() {
        CalculationTemplate task = new CalculationTemplate();
        task.setId(90L); task.setTemplateId(200L); task.setCompanyDeptId(100L); task.setInitiatorId(7L);
        return task;
    }

    private Template template() {
        Template template = new Template(); template.setId(200L); template.setDeptId(100L); return template;
    }

    private CalculationNode node(long id, long sourceId, int type, Long parentId) {
        CalculationNode node = new CalculationNode();
        node.setId(id); node.setNodeId(sourceId); node.setTypeId(type); node.setParentId(parentId);
        node.setIncludeInCalculation(true); return node;
    }

    private MonthlyCollectionDataService.CollectionCandidate candidate(CalculationNode node,
                                                                        int energy, int carbon, int status) {
        return candidate(node, energy, carbon, status, "PE_PF", "electricity", "MWh");
    }

    private MonthlyCollectionDataService.CollectionCandidate candidate(CalculationNode node,
            int energy, int carbon, int status, String subcategory, String energyCategory, String unit) {
        CalculationNodeData source = new CalculationNodeData(); source.setCalculationNodeId(node.getId());
        MonthlyCollectionNodeData row = new MonthlyCollectionNodeData();
        row.setYear(2026); row.setMonth(1); row.setCollectionPointType(1); row.setCollectionPointId(node.getNodeId());
        row.setEnergyCategoryL1(energyCategory); row.setEmissionSubcategory(subcategory);
        row.setMeasurementUnit(unit); row.setAdjustedEnergyValue(BigDecimal.valueOf(energy));
        row.setAdjustedCarbonEmission(BigDecimal.valueOf(carbon)); row.setDataStatus(status);
        return new MonthlyCollectionDataService.CollectionCandidate(node, source, row);
    }

    private void configureCategory(String subcategory, String unit, String parent) {
        when(factors.resolveSubcategoryCode(subcategory)).thenReturn(subcategory);
        when(conversions.convertToCalculationUnitRequired(eq(subcategory), eq(unit), any(BigDecimal.class)))
                .thenAnswer(call -> call.getArgument(2));
        when(conversions.convertRequired(eq(subcategory), eq(unit), eq(unit), any(BigDecimal.class)))
                .thenAnswer(call -> call.getArgument(3));
        CalcUnitDefault defaults = new CalcUnitDefault();
        defaults.setSubcategoryCode(subcategory); defaults.setCalculationUnit(unit); defaults.setReportUnit(unit);
        when(unitDefaults.findBySubcategoryCode(subcategory)).thenReturn(Optional.of(defaults));
        DataDictItem item = new DataDictItem(); item.setParentCode(parent);
        when(dictItems.findByItemCode(subcategory)).thenReturn(Optional.of(item));
    }
}
