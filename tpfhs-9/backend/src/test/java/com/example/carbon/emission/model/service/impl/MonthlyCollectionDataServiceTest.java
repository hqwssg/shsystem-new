package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class MonthlyCollectionDataServiceTest {

    @Mock CalculationNodeRepository calculationNodes;
    @Mock CalculationNodeDataRepository calculationData;
    @Mock MeterInfoRepository meters;
    @Mock FossilFuelMeterInfoRepository fossilMeters;
    @Mock PurchasedHeatMeterInfoRepository heatMeters;
    @Mock EnergyMeasurementCalculator calculator;
    @Mock FactorDimensionService factorDimensions;
    @Mock MonthlyCollectionDataWriter writer;
    MonthlyCollectionDataService service;

    @BeforeEach
    void setUp() {
        service = new MonthlyCollectionDataService(calculationNodes, calculationData, meters, fossilMeters,
                heatMeters, calculator, factorDimensions, writer, new ObjectMapper());
    }

    @Test
    void publishesOneRowForEachCompleteMonthUsingTheTaskFactorSnapshot() {
        CalculationTemplate task = task(90L, 2, LocalDate.of(2026, 1, 1), LocalDate.of(2026, 3, 31));
        Template template = template("{\"cycleType\":\"MONTHLY\"}");
        CalculationNode node = node(101L, "采集节点");
        CalculationNodeData source = source(101L, 1, 36L);
        when(calculationNodes.findByCalculationTemplateId(90L)).thenReturn(List.of(node));
        when(calculationData.findByCalculationNodeIdIn(anyCollection())).thenReturn(List.of(source));
        MeterInfo meter = new MeterInfo();
        meter.setId(36L); meter.setEnergyAttributionDeptId(8L); meter.setEnergyAttributionStationId(9L);
        when(meters.findById(36L)).thenReturn(Optional.of(meter));
        when(calculator.calculate(eq(1), eq(36L), eq(1), any(LocalDate.class), any(LocalDate.class)))
                .thenAnswer(invocation -> result(invocation.getArgument(3), invocation.getArgument(4)));
        when(factorDimensions.calculate(eq("外购电力"), any(BigDecimal.class), eq("MWh"),
                eq(new BigDecimal("0.500000")), eq("tCO2/MWh")))
                .thenReturn(new FactorDimensionService.CarbonResult(new BigDecimal("10"),
                        new BigDecimal("5"), "tCO2/MWh", "MWh"));

        assertThat(service.publish(task, template, true)).isEqualTo(3);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<MonthlyCollectionNodeData>> captor = ArgumentCaptor.forClass(List.class);
        verify(writer).replace(captor.capture());
        assertThat(captor.getValue()).extracting(MonthlyCollectionNodeData::getMonth)
                .containsExactly(1, 2, 3);
        assertThat(captor.getValue()).allSatisfy(row -> {
            assertThat(row.getCollectionPointId()).isEqualTo(36L);
            assertThat(row.getCarbonEmission()).isEqualByComparingTo("5.000000000");
            assertThat(row.getEnergyAttributionDeptId()).isEqualTo(8L);
            assertThat(row.getEnergyAttributionStationId()).isEqualTo(9L);
        });
    }

    @Test
    void automaticDailyAndWeeklyTasksDoNotPublishEvenIfDatesArePresent() {
        CalculationTemplate task = task(90L, 1, LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 1));

        assertThat(service.publish(task, template("{\"cycleType\":\"DAILY\"}"), true)).isZero();
        assertThat(service.publish(task, template("{\"cycleType\":\"WEEKLY\"}"), true)).isZero();

        verifyNoInteractions(writer, calculationNodes, calculationData);
    }

    @Test
    void rejectsLegacyDuplicatePointsInsteadOfChoosingOneNode() {
        CalculationTemplate task = task(90L, 2, LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 31));
        when(calculationNodes.findByCalculationTemplateId(90L))
                .thenReturn(List.of(node(101L, "节点甲"), node(102L, "节点乙")));
        when(calculationData.findByCalculationNodeIdIn(anyCollection()))
                .thenReturn(List.of(source(101L, 1, 36L), source(102L, 1, 36L)));

        assertThatThrownBy(() -> service.publish(task, template("{}"), true))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("节点甲").hasMessageContaining("节点乙");
        verifyNoInteractions(writer);
    }

    @Test
    void incompleteCalendarRangeDoesNotPublish() {
        CalculationTemplate task = task(90L, 2, LocalDate.of(2026, 1, 2), LocalDate.of(2026, 1, 31));
        assertThat(service.publish(task, template("{}"), true)).isZero();
        verifyNoInteractions(writer);
    }

    private CalculationTemplate task(long id, int initiator, LocalDate start, LocalDate end) {
        CalculationTemplate task = new CalculationTemplate();
        task.setId(id); task.setStatus(CalculationTemplate.STATUS_SUCCESS); task.setTaskInitiator(initiator);
        task.setInitiatorId(7L); task.setCalculationCycleStartDate(start); task.setCalculationCycleEndDate(end);
        return task;
    }

    private Template template(String config) {
        Template template = new Template(); template.setTaskConfig(config); return template;
    }

    private CalculationNode node(long id, String name) {
        CalculationNode node = new CalculationNode();
        node.setId(id); node.setName(name); node.setTypeId(3); node.setIncludeInCalculation(true);
        return node;
    }

    private CalculationNodeData source(long nodeId, int type, long pointId) {
        CalculationNodeData data = new CalculationNodeData();
        data.setCalculationNodeId(nodeId); data.setCollectionPointType(type); data.setCollectionPointId(pointId);
        data.setEmissionCategory("购入的电力"); data.setEmissionSubcategory("外购电力");
        data.setCarbonEmissionFactor(new BigDecimal("0.500000"));
        data.setCarbonEmissionFactorUnit("tCO2/MWh"); data.setMeasurementUnit("MWh");
        data.setIsCumulative(1); data.setIsMobileSource(0); data.setTotalEmissionCalcMethod(1);
        return data;
    }

    private EnergyMeasurementCalculator.Result result(LocalDate start, LocalDate end) {
        EnergyMeasurementCalculator.Result result = new EnergyMeasurementCalculator.Result();
        result.setEnergyMeasurementValue(new BigDecimal("10.000000"));
        result.setAdjustedEnergyValue(new BigDecimal("10.000000"));
        result.setDataStatus(1); result.setCollectionRecordStartDate(start); result.setCollectionRecordEndDate(end);
        result.setRolloverApplied(false);
        return result;
    }
}
