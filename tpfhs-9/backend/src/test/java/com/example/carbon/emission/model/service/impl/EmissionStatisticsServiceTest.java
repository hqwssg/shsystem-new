package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.DefaultFactor;
import com.example.carbon.emission.model.repository.DefaultFactorRepository;
import com.example.carbon.emission.model.security.CollectionScopeService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabase;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabaseBuilder;
import org.springframework.jdbc.datasource.embedded.EmbeddedDatabaseType;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class EmissionStatisticsServiceTest {
    private EmissionStatisticsService service;

    @BeforeEach
    void setUp() {
        service = new EmissionStatisticsService(mock(JdbcTemplate.class),
                mock(CollectionScopeService.class), mock(FactorDimensionService.class),
                mock(EffectiveFactorResolver.class));
    }

    @Test
    void rejectsInvalidDateRangeBeforeQueryingDatabase() {
        EmissionStatisticsService.Criteria criteria = new EmissionStatisticsService.Criteria();
        criteria.startDate = LocalDate.of(2026, 2, 1);
        criteria.endDate = LocalDate.of(2026, 1, 1);

        assertThatThrownBy(() -> service.query(criteria))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("开始日期不能晚于结束日期");
    }

    @Test
    void rejectsUnsupportedDashboardFilters() {
        EmissionStatisticsService.Criteria criteria = new EmissionStatisticsService.Criteria();
        criteria.energyType = 4;

        assertThatThrownBy(() -> service.dashboard(criteria))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("能源类型仅支持");
    }

    @Test
    void usesSelectedTemplateDefaultsInDetailsAndEveryChart() {
        try (StatisticsFixture fixture = new StatisticsFixture()) {
            fixture.template(1, 101);
            fixture.template(2, 102);
            fixture.defaultFactor(101, "PE_PF", "0.5", "tCO2/MWh", 1);
            fixture.defaultFactor(101, "PH_HD", "0.1", "tCO2/GJ", 1);
            fixture.defaultFactor(102, "PE_PF", "0.8", "tCO2/MWh", 1);
            fixture.node(11, 1, 1, 31, null, null);
            fixture.node(12, 1, 3, 32, null, null);
            fixture.node(21, 2, 1, 31, null, null);
            fixture.reading(1, 1, 31, "10", "PE_PF", "MWh");
            fixture.reading(2, 3, 32, "30", "PH_HD", "GJ");

            List<Map<String, Object>> rows = rows(fixture.service.query(criteria(1)));
            assertThat(rows).hasSize(2);
            assertAmount(rows.get(0), "0.5", "5");
            assertAmount(rows.get(1), "0.1", "3");
            Map<String, Object> dashboard = fixture.service.dashboard(criteria(1));
            assertThat(summary(dashboard)).containsEntry("totalEmission", new BigDecimal("8.000000000"))
                    .containsEntry("factorMissingCount", 0L);
            assertThat(dashboard.get("trend")).isEqualTo(List.of(series("period", "2026-10", "8")));
            assertThat(dashboard.get("energyMix")).isEqualTo(List.of(
                    series("name", "外购热力", "3"), series("name", "购入电力", "5")));
            assertThat(dashboard.get("sourceMix")).isEqualTo(List.of(series("name", "人工采集", "8")));

            List<Map<String, Object>> otherRows = rows(fixture.service.query(criteria(2)));
            assertThat(otherRows).hasSize(1);
            assertAmount(otherRows.get(0), "0.8", "8");
        }
    }

    @Test
    void usesCompleteOverrideAndDistinguishesRealZeroFromUnavailableEmission() {
        try (StatisticsFixture fixture = new StatisticsFixture()) {
            fixture.template(1, 101);
            fixture.defaultFactor(101, "PE_PF", "0.5", "tCO2/MWh", 1);
            fixture.defaultFactor(101, "PH_HD", "0.1", "tCO2/GJ", 0);
            fixture.node(11, 1, 1, 31, "0.7", "tCO2/MWh");
            fixture.node(12, 1, 1, 32, "0.7", null);
            fixture.node(13, 1, 1, 33, null, null);
            fixture.node(14, 1, 1, 34, null, null);
            fixture.node(15, 1, 3, 35, null, null);
            fixture.reading(1, 1, 31, "10", "PE_PF", "MWh");
            fixture.reading(2, 1, 32, "10", "PE_PF", "MWh");
            fixture.reading(3, 1, 33, "0", "PE_PF", "MWh");
            fixture.reading(4, 1, 34, "10", "PE_PF", "unsupported");
            fixture.reading(5, 3, 35, "30", "PH_HD", "GJ");

            List<Map<String, Object>> rows = rows(fixture.service.query(criteria(1)));
            assertThat(rows).hasSize(5);
            assertAmount(rows.get(0), "0.7", "7");
            assertAmount(rows.get(2), "0.5", "0");
            for (int index : List.of(1, 3, 4)) {
                assertThat(rows.get(index)).containsEntry("calculatedValue", null).containsEntry("factorMissing", true);
            }
            assertThat(summary(fixture.service.dashboard(criteria(1)))).containsEntry("factorMissingCount", 3L)
                    .containsEntry("totalEmission", new BigDecimal("7.000000000"));
        }
    }

    private static EmissionStatisticsService.Criteria criteria(long templateId) {
        EmissionStatisticsService.Criteria criteria = new EmissionStatisticsService.Criteria();
        criteria.templateId = templateId;
        criteria.sortDirection = "ASC";
        return criteria;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rows(Map<String, Object> page) {
        return (List<Map<String, Object>>) page.get("content");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> summary(Map<String, Object> dashboard) {
        return (Map<String, Object>) dashboard.get("summary");
    }

    private static Map<String, Object> series(String key, String label, String value) {
        return Map.of(key, label, "value", new BigDecimal(value).setScale(9));
    }

    private static void assertAmount(Map<String, Object> row, String factor, String carbon) {
        assertThat((BigDecimal) row.get("emissionFactor")).isEqualByComparingTo(factor);
        assertThat((BigDecimal) row.get("calculatedValue")).isEqualByComparingTo(carbon);
        assertThat(row).containsEntry("factorMissing", false);
    }

    private static class StatisticsFixture implements AutoCloseable {
        private final EmbeddedDatabase database = new EmbeddedDatabaseBuilder()
                .generateUniqueName(true).setType(EmbeddedDatabaseType.H2).build();
        private final JdbcTemplate jdbc = new JdbcTemplate(database);
        private final DefaultFactorRepository defaults = mock(DefaultFactorRepository.class);
        private final EmissionStatisticsService service;

        StatisticsFixture() {
            jdbc.execute("create table emission_template (id bigint primary key, factor_template_id bigint)");
            jdbc.execute("create table emission_node (id bigint primary key, template_id bigint, name varchar(80))");
            jdbc.execute("""
                    create table emission_node_config (id bigint primary key, node_id bigint, collection_point_type int,
                    collection_point_id bigint, carbon_emission_factor decimal(15,6), carbon_emission_factor_unit varchar(40))
                    """);
            jdbc.execute("""
                    create table emission_collection_record (id bigint primary key, collection_point_type int,
                    collection_point_id bigint, reading_value decimal(15,6), collection_time timestamp,
                    external_quality varchar(40), collection_point_name varchar(40), emission_subcategory varchar(40),
                    measurement_unit varchar(40), meter_reading_method int, is_cumulative int,
                    review_comment varchar(80), collection_status int, workflow_status varchar(40))
                    """);
            CollectionScopeService scopes = mock(CollectionScopeService.class);
            when(scopes.canView(anyString(), anyString(), any())).thenReturn(true);
            FactorDimensionService dimensions = mock(FactorDimensionService.class);
            when(dimensions.resolveSubcategoryCode(anyString())).thenAnswer(call -> call.getArgument(0));
            when(dimensions.calculate(anyString(), any(), anyString(), any(), anyString())).thenAnswer(call -> {
                BigDecimal amount = call.getArgument(1);
                String activityUnit = call.getArgument(2);
                BigDecimal factor = call.getArgument(3);
                String factorUnit = call.getArgument(4);
                if (!factorUnit.equals("tCO2/" + activityUnit)) {
                    throw new IllegalStateException("no conversion");
                }
                return new FactorDimensionService.CarbonResult(amount, amount.multiply(factor), factorUnit, activityUnit);
            });
            service = new EmissionStatisticsService(jdbc, scopes, dimensions,
                    new EffectiveFactorResolver(defaults, dimensions));
        }

        void template(long id, long factorTemplateId) {
            jdbc.update("insert into emission_template values (?, ?)", id, factorTemplateId);
        }

        void defaultFactor(long id, String subcategory, String value, String unit, int status) {
            DefaultFactor factor = new DefaultFactor();
            factor.setFactorValue(new BigDecimal(value));
            factor.setFactorUnit(unit);
            factor.setStatus(status);
            when(defaults.findByTemplateIdAndSubcategoryCode(id, subcategory)).thenReturn(Optional.of(factor));
        }

        void node(long id, long templateId, int type, long point, String override, String unit) {
            jdbc.update("insert into emission_node values (?, ?, ?)", id, templateId, "node " + id);
            jdbc.update("insert into emission_node_config values (?, ?, ?, ?, ?, ?)",
                    id, id, type, point, override == null ? null : new BigDecimal(override), unit);
        }

        void reading(long id, int type, long point, String value, String subcategory, String unit) {
            jdbc.update("""
                    insert into emission_collection_record values
                    (?, ?, ?, ?, ?, null, 'point', ?, ?, 0, 0, null, 1, 'APPROVED')
                    """, id, type, point, new BigDecimal(value), LocalDate.of(2026, 10, (int) id).atStartOfDay(),
                    subcategory, unit);
        }

        @Override
        public void close() {
            database.shutdown();
        }
    }

    @Test
    void rejectsUnsupportedSurfaceGranularity() {
        assertThatThrownBy(() -> service.surface(new EmissionStatisticsService.Criteria(), "year"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("granularity");
    }
}
