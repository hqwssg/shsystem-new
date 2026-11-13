package com.ruoyi.carbon.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;
import com.ruoyi.carbon.analysis.domain.AnalysisNode;

class AnalysisAggregatorTest
{
    private final AnalysisAggregator aggregator = new AnalysisAggregator();

    @Test
    void monthsSumIntoQuarterWhenNoQuarterCalculation()
    {
        AnalysisNode branch = node(1L, 10L, null, "肃宁分公司", "BRANCH");
        List<AnalysisFact> facts = List.of(
                fact(1L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 1L, 10L, "肃宁分公司", "kWh", "100", "1"),
                fact(2L, "2025-02-01", "2025-02-28", "2025-03-01 00:00:00", 2L, 10L, "肃宁分公司", "kWh", "50", "2"));
        Map<String, Object> result = aggregator.query(List.of(branch), facts, "quarter", LocalDate.parse("2025-01-01"),
                LocalDate.parse("2025-03-31"), "BRANCH", null, "total", null, null);
        Map<String, Object> row = row(result);
        assertEquals("2025-Q1", row.get("period"));
        assertEquals(0, new BigDecimal("150").compareTo(energy(row)));
        assertEquals(0, new BigDecimal("3").compareTo((BigDecimal) row.get("carbon")));
        assertTrue(notices(result).stream().anyMatch(item -> item.contains("缺少的月份")));
    }

    @Test
    void quarterCalculationReplacesMonths()
    {
        List<AnalysisFact> facts = List.of(
                fact(1L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 1L, 10L, "肃宁分公司", "kWh", "100", "1"),
                fact(2L, "2025-01-01", "2025-03-31", "2025-04-01 00:00:00", 2L, 10L, "肃宁分公司", "kWh", "80", "4"));
        Map<String, Object> result = aggregator.query(List.of(), facts, "quarter", LocalDate.parse("2025-01-01"),
                LocalDate.parse("2025-03-31"), "BRANCH", null, "total", null, null);
        assertEquals(0, new BigDecimal("80").compareTo(energy(row(result))));
    }

    @Test
    void laterCalculationWinsTheSameMonth()
    {
        List<AnalysisFact> facts = List.of(
                fact(1L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 1L, 10L, "肃宁分公司", "kWh", "100", "1"),
                fact(2L, "2025-01-05", "2025-01-20", "2025-02-03 00:00:00", 2L, 10L, "肃宁分公司", "kWh", "40", "2"));
        Map<String, Object> result = aggregator.query(List.of(), facts, "month", LocalDate.parse("2025-01-01"),
                LocalDate.parse("2025-01-31"), "BRANCH", null, "total", null, null);
        assertEquals(0, new BigDecimal("40").compareTo(energy(row(result))));
    }

    @Test
    void yearSpanIsNotSplitIntoMonths()
    {
        List<AnalysisFact> facts = List.of(
                fact(1L, "2025-01-01", "2025-12-31", "2026-01-02 00:00:00", 1L, 10L, "肃宁分公司", "kWh", "900", "9"));
        Map<String, Object> result = aggregator.query(List.of(), facts, "month", LocalDate.parse("2025-01-01"),
                LocalDate.parse("2025-12-31"), "BRANCH", null, "total", null, null);
        assertTrue(((List<?>) result.get("rows")).isEmpty());
        assertTrue(notices(result).stream().anyMatch(item -> item.contains("不能拆进单月")));
    }

    @Test
    void differentUnitsStaySeparateAndCarbonAdds()
    {
        List<AnalysisFact> facts = List.of(
                fact(1L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 1L, 10L, "肃宁分公司", "kWh", "100", "1", "PE_PF", "外购电力"),
                fact(1L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 1L, 10L, "肃宁分公司", "L", "20", "3", "FF_D", "柴油"));
        Map<String, Object> result = aggregator.query(List.of(), facts, "month", LocalDate.parse("2025-01-01"),
                LocalDate.parse("2025-01-31"), "BRANCH", null, "total", null, null);
        Map<String, Object> row = row(result);
        assertEquals(2, energies(row).size());
        assertEquals(0, new BigDecimal("4").compareTo((BigDecimal) row.get("carbon")));
        assertEquals("carbon", result.get("chartMetric"));
    }

    @Test
    void yearOnYearRateIsEmptyWhenPreviousIsZero()
    {
        List<AnalysisFact> current = List.of(
                fact(2L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 2L, 10L, "肃宁分公司", "kWh", "30", "3"));
        List<AnalysisFact> previous = List.of(
                fact(1L, "2024-01-01", "2024-01-31", "2024-02-01 00:00:00", 1L, 10L, "肃宁分公司", "kWh", "0", "0"));
        Map<String, Object> now = aggregator.query(List.of(), current, "month", LocalDate.parse("2025-01-01"),
                LocalDate.parse("2025-01-31"), "BRANCH", null, "total", null, null);
        Map<String, Object> then = aggregator.query(List.of(), previous, "month", LocalDate.parse("2024-01-01"),
                LocalDate.parse("2024-01-31"), "BRANCH", null, "total", null, null);
        Map<String, Object> compared = aggregator.compare(now, then, true);
        Map<String, Object> row = row(compared);
        assertNull(row.get("carbonRate"));
        assertEquals(0, new BigDecimal("3").compareTo((BigDecimal) row.get("carbonDelta")));
    }

    @Test
    void stationUnderSelectedBranchIsKept()
    {
        AnalysisNode branch = node(1L, 10L, null, "肃宁分公司", "BRANCH");
        AnalysisNode other = node(2L, 20L, null, "原平分公司", "BRANCH");
        AnalysisNode station = node(3L, 30L, 1L, "甲站", "STATION");
        AnalysisNode outside = node(4L, 40L, 2L, "乙站", "STATION");
        List<AnalysisFact> facts = List.of(
                fact(8L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 3L, 30L, "甲站", "kWh", "10", "1"),
                fact(8L, "2025-01-01", "2025-01-31", "2025-02-01 00:00:00", 4L, 40L, "乙站", "kWh", "99", "9"));
        facts.get(0).setNodeCategory("STATION");
        facts.get(1).setNodeCategory("STATION");
        Map<String, Object> result = aggregator.query(List.of(branch, other, station, outside), facts, "month",
                LocalDate.parse("2025-01-01"), LocalDate.parse("2025-01-31"), "STATION", 10L, "total", null, null);
        assertEquals(1, ((List<?>) result.get("rows")).size());
        assertEquals("甲站", row(result).get("orgName"));
    }

    private static AnalysisNode node(Long calcNodeId, Long sourceNodeId, Long parentCalcNodeId, String name, String category)
    {
        AnalysisNode node = new AnalysisNode();
        node.setTemplateId(1L);
        node.setCalcNodeId(calcNodeId);
        node.setSourceNodeId(sourceNodeId);
        node.setParentCalcNodeId(parentCalcNodeId);
        node.setNodeName(name);
        node.setNodeCategory(category);
        return node;
    }

    private static AnalysisFact fact(Long templateId, String start, String end, String finished, Long calcNodeId,
            Long sourceNodeId, String name, String unit, String energy, String carbon)
    {
        return fact(templateId, start, end, finished, calcNodeId, sourceNodeId, name, unit, energy, carbon, "PE_PF", "外购电力");
    }

    private static AnalysisFact fact(Long templateId, String start, String end, String finished, Long calcNodeId,
            Long sourceNodeId, String name, String unit, String energy, String carbon, String subcategory, String subcategoryName)
    {
        AnalysisFact fact = new AnalysisFact();
        fact.setTemplateId(templateId);
        fact.setCycleStart(start);
        fact.setCycleEnd(end);
        fact.setCalculationEndTime(finished);
        fact.setCalcNodeId(calcNodeId);
        fact.setSourceNodeId(sourceNodeId);
        fact.setNodeName(name);
        fact.setNodeCategory("BRANCH");
        fact.setSubcategory(subcategory);
        fact.setSubcategoryName(subcategoryName);
        fact.setUnitCode(unit);
        fact.setUnitName(unit);
        fact.setEnergyValue(new BigDecimal(energy));
        fact.setCarbonValue(new BigDecimal(carbon));
        return fact;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> row(Map<String, Object> result)
    {
        return ((List<Map<String, Object>>) result.get("rows")).get(0);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> energies(Map<String, Object> row)
    {
        return (List<Map<String, Object>>) row.get("energies");
    }

    private static BigDecimal energy(Map<String, Object> row)
    {
        return (BigDecimal) energies(row).get(0).get("energy");
    }

    @SuppressWarnings("unchecked")
    private static List<String> notices(Map<String, Object> result)
    {
        return (List<String>) result.get("notices");
    }
}
