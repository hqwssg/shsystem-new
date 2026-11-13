package com.example.carbon.emission.model.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TaskScheduleConfigServiceTest {

    private final TaskScheduleConfigService service = new TaskScheduleConfigService(new ObjectMapper());

    @org.junit.jupiter.api.Test
    void automaticCalculationMustBeExplicitlyEnabled() {
        org.junit.jupiter.api.Assertions.assertFalse(service.isAutoCalculationEnabled(null));
        org.junit.jupiter.api.Assertions.assertFalse(service.isAutoCalculationEnabled("{}"));
        org.junit.jupiter.api.Assertions.assertFalse(service.isAutoCalculationEnabled(
                "{\"autoCalculationEnabled\":\"true\"}"));
        org.junit.jupiter.api.Assertions.assertTrue(service.isAutoCalculationEnabled(
                "{\"autoCalculationEnabled\":true}"));
    }

    @Test
    void rejectsInvalidScheduleFields() {
        String invalid = """
                {"cycleType":"DAILY","executionTime":"","startDate":"2026-09-20",
                 "endDate":"2026-09-19","delayDays":-1,"interval":0}
                """;
        assertThatThrownBy(() -> service.validate(invalid))
                .isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void calculatesDailyCycleFromValidatedConfig() {
        String valid = """
                {"cycleType":"DAILY","executionTime":"08:30","startDate":"2026-01-01",
                 "endDate":"2026-12-31","delayDays":1,"interval":1}
                """;
        LocalDate[] cycle = service.calculateCycle(valid, LocalDate.of(2026, 9, 21));
        assertThat(cycle).containsExactly(LocalDate.of(2026, 9, 19), LocalDate.of(2026, 9, 19));
    }

    @Test
    void acceptsSchedulesWithoutStartAndEndDates() {
        String valid = """
                {"cycleType":"DAILY","executionTime":"08:30","startDate":null,
                 "endDate":null,"delayDays":0,"interval":1}
                """;

        assertThat(service.normalize(valid)).contains("\"startDate\":null", "\"endDate\":null");
    }

    @Test
    void acceptsOnlyStartOrOnlyEndDate() {
        String onlyStart = """
                {"cycleType":"DAILY","executionTime":"08:30","startDate":"2026-01-01",
                 "endDate":null,"delayDays":0,"interval":1}
                """;
        String onlyEnd = """
                {"cycleType":"DAILY","executionTime":"08:30","startDate":null,
                 "endDate":"2026-12-31","delayDays":0,"interval":1}
                """;

        assertThat(service.normalize(onlyStart)).contains("2026-01-01");
        assertThat(service.normalize(onlyEnd)).contains("2026-12-31");
    }

    @Test
    void rejectsInvalidAndReversedOptionalDates() {
        String invalid = """
                {"cycleType":"DAILY","executionTime":"08:30","startDate":"not-a-date",
                 "endDate":null,"delayDays":0,"interval":1}
                """;
        String reversed = """
                {"cycleType":"DAILY","executionTime":"08:30","startDate":"2026-12-31",
                 "endDate":"2026-01-01","delayDays":0,"interval":1}
                """;

        assertThatThrownBy(() -> service.normalize(invalid))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("ISO");
        assertThatThrownBy(() -> service.normalize(reversed))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("不能晚于");
    }

    @Test
    void normalizesLegacyWeekDaysToCanonicalWeekdays() {
        String legacy = """
                {"cycleType":"WEEKLY","executionTime":"08:30","startDate":"2026-01-01",
                 "endDate":"2026-12-31","delayDays":0,"interval":1,"weekDays":[1]}
                """;
        String normalized = service.normalize(legacy);
        assertThat(normalized).contains("\"weekdays\":[1]").doesNotContain("weekDays");
    }

    @Test
    void rejectsConflictingWeekdayAliases() {
        String conflicting = """
                {"cycleType":"WEEKLY","executionTime":"08:30","startDate":"2026-01-01",
                 "endDate":"2026-12-31","delayDays":0,"interval":1,
                 "weekdays":[1],"weekDays":[2]}
                """;
        assertThatThrownBy(() -> service.normalize(conflicting))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("weekDays与weekdays");
    }
}
