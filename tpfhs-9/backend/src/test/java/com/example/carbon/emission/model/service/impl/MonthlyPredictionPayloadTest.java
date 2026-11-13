package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.service.UnitConversionService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;

import java.math.BigDecimal;
import java.time.YearMonth;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class MonthlyPredictionPayloadTest {
    private static final YearMonth JANUARY = YearMonth.of(2026, 1);
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final UnitConversionService units = mock(UnitConversionService.class);

    @SuppressWarnings("unchecked")
    private MonthlyPredictionPayload mapper(String org, String traction, String auxiliary) {
        when(jdbc.query(anyString(), any(ResultSetExtractor.class), eq(3030L))).thenReturn(org);
        when(units.convertRequired(anyString(), anyString(), anyString(), any(BigDecimal.class)))
                .thenAnswer(call -> call.getArgument(3));
        return new MonthlyPredictionPayload(jdbc, units, traction, auxiliary);
    }

    @Test
    void jlgElectricityClosesAtStoragePrecisionAndOnlyReportedHeatIsSent() {
        var snapshot = new MonthlyPredictionOutbox.Snapshot(List.of(
                group(1, "EC01", "PE_PF", "MWh", "1.0000006"),
                group(2, "EC02", "PE_PF", "MWh", "2.0000006"),
                group(3, "EC03", "PE_PF", "MWh", "3"),
                group(4, "EC03", "PH_HD", "GJ", "50")), List.of(), true);
        var body = mapper("JLG", "EC01", "EC02,EC03").build(delivery(snapshot));
        assertThat(body).containsEntry("idempotency_key", "carbon-month-9");
        assertThat(records(body)).extracting(row -> row.get("var_id"))
                .containsExactly("ELEC_AUX", "ELEC_TOTAL", "ELEC_TRAC", "HEAT_REPORTED");
        assertThat(records(body).get(1).get("value")).isEqualTo(new BigDecimal("6.000002"));
    }

    @Test
    void missingGroupIsNotSentAsZeroAndRemainsPending() {
        var snapshot = new MonthlyPredictionOutbox.Snapshot(
                List.of(group(1, "EC02", "FF_D", "t", "0")),
                List.of(new MonthlyPredictionOutbox.Missing(2, 71, "EC02", "FF_D", 2, true)), false);
        var body = mapper("SNF", "", "").build(delivery(snapshot));
        assertThat(records(body)).isEmpty();
        assertThat(((Map<?, ?>) body.get("source_snapshot")).get("complete")).isEqualTo(false);
        assertThat(body.get("source_snapshot").toString()).contains("missing:DIESEL", "point:2:71:2");
    }

    @Test
    void unapprovedTractionMappingCannotSend() {
        var snapshot = new MonthlyPredictionOutbox.Snapshot(
                List.of(group(1, "EC01", "PE_PF", "MWh", "10")), List.of(), true);
        assertThatThrownBy(() -> mapper("JLG", "", "").build(delivery(snapshot)))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("机辆电力分组");
    }

    private static MonthlyPredictionOutbox.Delivery delivery(MonthlyPredictionOutbox.Snapshot snapshot) {
        return new MonthlyPredictionOutbox.Delivery(9, 3030, 3, JANUARY, 1, snapshot, null, 1);
    }

    private static MonthlyPredictionOutbox.Group group(long id, String category, String subcategory,
                                                       String unit, String value) {
        return new MonthlyPredictionOutbox.Group(id, category, subcategory, unit, new BigDecimal(value));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> records(Map<String, Object> body) {
        return (List<Map<String, Object>>) body.get("records");
    }
}
