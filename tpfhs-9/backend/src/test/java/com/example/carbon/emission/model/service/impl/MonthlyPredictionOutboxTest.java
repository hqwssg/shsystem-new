package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.YearMonth;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class MonthlyPredictionOutboxTest {
    @Test
    void missingPointUsesTheSameCanonicalGroupingAsTheCompanySnapshot() throws Exception {
        var jdbc = mock(JdbcTemplate.class);
        var factors = mock(FactorDimensionService.class);
        var json = new ObjectMapper();
        var outbox = new MonthlyPredictionOutbox(jdbc, json, factors);
        var point = new MonthlyCollectionNodeData();
        point.setCollectionPointType(2);
        point.setCollectionPointId(71L);
        point.setDataStatus(2);
        point.setEnergyCategoryL1(" EC02 ");
        point.setEmissionSubcategory("柴油");
        when(factors.resolveSubcategoryCode("柴油")).thenReturn("FF_D");
        var row = new MonthlyCompanyEnergySummary();
        row.setId(4L);
        row.setEnergyCategoryL1("EC02");
        row.setEmissionSubcategory("FF_D");
        row.setCalculationUnitCode("t");
        row.setStandardEnergyValue(BigDecimal.ZERO);
        row.setResultStatus(2);
        var month = YearMonth.of(2026, 1);

        outbox.record(1, 2, month, 1, List.of(row), List.of(point), Set.of());

        var encoded = ArgumentCaptor.forClass(String.class);
        verify(jdbc).update(startsWith("insert into emission_monthly_prediction_outbox"), eq(1L), eq(2L),
                eq(month.atDay(1)), eq(1), encoded.capture(), eq("DISABLED"), any(Timestamp.class));
        var snapshot = json.readValue(encoded.getValue(), MonthlyPredictionOutbox.Snapshot.class);
        var group = snapshot.groups().get(0);
        assertThat(snapshot.missing()).containsExactly(
                new MonthlyPredictionOutbox.Missing(2, 71, group.category(), group.subcategory(), 2, true));
    }
}
