package com.ruoyi.carbon.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ScreenDashboardServiceTest
{
    @Test
    void overallUsesBranchesAndLeavesMissingChartsEmpty()
    {
        List<Map<String, Object>> branchYears = List.of(yearRow(10L, "肃宁分公司", "2026", "10"), yearRow(10L, "肃宁分公司", "2025", "5"));
        List<Map<String, Object>> stationYears = List.of(yearRow(21L, "黄骅港站", "2026", "3"));
        List<Map<String, Object>> branchMonths = List.of(monthRow(10L, "肃宁分公司", "2026-12", "1"), monthRow(10L, "肃宁分公司", "2026-10", "2"));
        List<Map<String, Object>> categories = List.of(categoryRow(10L, "肃宁分公司", "2026", "柴油", "3"));
        Map<String, Object> dashboard = ScreenDashboardService.build(2026, branchYears, stationYears, branchMonths, List.of(), categories, List.of());

        assertEquals("统计周期：2026年1月—2026年12月", dashboard.get("periodLabel"));
        Map<String, Object> overall = bucket(dashboard, "overall");
        assertEquals(10d, kpi(overall, "yearTotal"));
        assertEquals(1d, kpi(overall, "monthTotal"));
        assertEquals(100d, kpi(overall, "yoyPercent"));
        assertEquals(1, kpi(overall, "pointCount"));
        List<Map<String, Object>> line = line(overall);
        assertEquals(12, line.size());
        assertNull(line.get(0).get("actual"));
        assertNull(line.get(11).get("forecast"));
        assertEquals(1d, line.get(11).get("actual"));
        assertEquals(2d, line.get(9).get("actual"));
        assertEquals(List.of("柴油"), pieNames(overall, "source"));
        assertTrue(pieNames(overall, "type").isEmpty());
        assertTrue(pieNames(overall, "segment").isEmpty());
        assertEquals(List.of(2026), surface(overall).get("years"));
        @SuppressWarnings("unchecked")
        List<List<Double>> values = (List<List<Double>>) surface(overall).get("values");
        assertEquals(0d, values.get(0).get(0));
        assertEquals(2d, values.get(0).get(9));
        @SuppressWarnings("unchecked")
        List<List<String>> rank = (List<List<String>>) dashboard.get("rank");
        assertEquals(List.of("黄骅港站", "3", "0"), rank.get(0));
        @SuppressWarnings("unchecked")
        Map<String, Object> mapped = (Map<String, Object>) ((Map<?, ?>) dashboard.get("mapEmissions")).get("黄骅港站");
        assertEquals(3d, mapped.get("carbonEmission"));
        assertEquals(0, mapped.get("carbonIntensity"));
    }

    @Test
    void sceneAndSegmentUseEnergyCategoryNames()
    {
        Map<String, Object> energy = new LinkedHashMap<>();
        energy.put("subcategoryName", "柴油");
        energy.put("categoryL1", "EC02");
        energy.put("categoryL2", "EC0202");
        energy.put("carbon", new BigDecimal("3"));
        Map<String, Object> other = new LinkedHashMap<>();
        other.put("subcategoryName", "外购电力");
        other.put("categoryL1", "EC01");
        other.put("categoryL2", "未入字典");
        other.put("carbon", new BigDecimal("1"));
        Map<String, Object> row = yearRow(10L, "肃宁分公司", "2026", "4");
        row.put("energies", List.of(energy, other));
        Map<String, String> names = Map.of("EC01", "生产用能", "EC02", "生产辅助用能", "EC0202", "机车运用与检修（机务）");
        Map<String, Object> dashboard = ScreenDashboardService.build(2026, List.of(yearRow(10L, "肃宁分公司", "2026", "4")),
                List.of(), List.of(), List.of(), List.of(row), List.of(), names);
        Map<String, Object> overall = bucket(dashboard, "overall");
        assertEquals(List.of("柴油", "外购电力"), pieNames(overall, "source"));
        assertEquals(List.of("生产辅助用能", "生产用能"), pieNames(overall, "type"));
        assertEquals(List.of("机车运用与检修（机务）", "未入字典"), pieNames(overall, "segment"));
    }

    @Test
    void missingPreviousYearKeepsYoyAtZero()
    {
        Map<String, Object> dashboard = ScreenDashboardService.build(2026, List.of(yearRow(10L, "肃宁分公司", "2026", "10")),
                List.of(), List.of(), List.of(), List.of(), List.of());
        assertEquals(0d, kpi(bucket(dashboard, "overall"), "yoyPercent"));
        assertEquals("统计周期：2026年", dashboard.get("periodLabel"));
        assertTrue(line(bucket(dashboard, "overall")).isEmpty());
    }

    @Test
    void unknownStationIsNotInvented()
    {
        Map<String, Object> dashboard = ScreenDashboardService.emptyDashboard();
        assertEquals("统计周期：", dashboard.get("periodLabel"));
        assertTrue(((Map<?, ?>) dashboard.get("stations")).isEmpty());
        assertTrue(((List<?>) dashboard.get("rank")).isEmpty());
    }

    @Test
    void stationFactsRecoverOverallWhenHistoricalBranchSummaryIsZero()
    {
        List<Map<String, Object>> branches = List.of(yearRow(10L, "肃宁分公司", "2026", "0"));
        List<Map<String, Object>> stations = List.of(
                yearRow(21L, "黄骅港站", "2026", "3"),
                yearRow(22L, "肃宁北站", "2026", "2"));
        List<Map<String, Object>> stationMonths = List.of(monthRow(21L, "黄骅港站", "2026-10", "3"));
        List<Map<String, Object>> stationCategories = List.of(categoryRow(21L, "黄骅港站", "2026", "柴油", "3"));

        Map<String, Object> dashboard = ScreenDashboardService.build(
                2026, branches, stations, List.of(), stationMonths, List.of(), stationCategories);

        Map<String, Object> overall = bucket(dashboard, "overall");
        assertEquals(5d, kpi(overall, "yearTotal"));
        assertEquals(3d, kpi(overall, "monthTotal"));
        assertEquals(List.of("柴油"), pieNames(overall, "source"));
    }

    private static Map<String, Object> yearRow(long id, String name, String period, String carbon)
    {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("orgId", id);
        row.put("orgName", name);
        row.put("period", period);
        row.put("carbon", new BigDecimal(carbon));
        row.put("energies", List.of());
        return row;
    }

    private static Map<String, Object> monthRow(long id, String name, String period, String carbon)
    {
        return yearRow(id, name, period, carbon);
    }

    private static Map<String, Object> categoryRow(long id, String name, String period, String variety, String carbon)
    {
        Map<String, Object> energy = new LinkedHashMap<>();
        energy.put("subcategoryName", variety);
        energy.put("carbon", new BigDecimal(carbon));
        Map<String, Object> row = yearRow(id, name, period, carbon);
        row.put("energies", List.of(energy));
        return row;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> bucket(Map<String, Object> dashboard, String key)
    {
        return (Map<String, Object>) dashboard.get(key);
    }

    @SuppressWarnings("unchecked")
    private static Object kpi(Map<String, Object> bucket, String field)
    {
        return ((Map<String, Object>) bucket.get("kpi")).get(field);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> line(Map<String, Object> bucket)
    {
        return (List<Map<String, Object>>) ((Map<String, Object>) bucket.get("line")).get("source");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> surface(Map<String, Object> bucket)
    {
        return (Map<String, Object>) bucket.get("surface");
    }

    @SuppressWarnings("unchecked")
    private static List<String> pieNames(Map<String, Object> bucket, String kind)
    {
        Map<String, Object> pies = (Map<String, Object>) bucket.get("pies");
        Map<String, Object> pie = (Map<String, Object>) pies.get(kind);
        List<String> names = new ArrayList<>();
        for (Map<String, Object> slice : (List<Map<String, Object>>) pie.get("source")) names.add(String.valueOf(slice.get("name")));
        return names;
    }
}
