package com.ruoyi.carbon.analysis.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.analysis.mapper.AnalysisMapper;
import com.ruoyi.carbon.analysis.mapper.ManagementDashboardMapper;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;

class ManagementDashboardServiceTest {
    private Map<String, Object> task(long id, String start, String end, int status, int problems) {
        Map<String, Object> t = new LinkedHashMap<>();
        t.put("id", id); t.put("companyId", 3030L); t.put("companyName", "机辆分公司");
        t.put("start", start); t.put("end", end); t.put("status", status);
        t.put("completed", "2026-10-26 10:00:00"); t.put("dataCount", 1); t.put("problemCount", problems); t.put("factorMissingCount", 0);
        return t;
    }
    private Map<String, Object> build(List<Map<String, Object>> tasks, List<Map<String, Object>> annual) {
        return ManagementDashboardService.build(2025, List.of(Map.of("id", 3030L, "name", "机辆分公司")), List.of(2025), null, tasks, annual, List.of());
    }
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> cells(Map<String, Object> result) {
        return (List<Map<String, Object>>)((List<Map<String, Object>>)result.get("coverage")).get(0).get("cells");
    }
    @Test void annualTaskDoesNotInventMonthlyCoverage() {
        Map<String, Object> result = build(List.of(task(1, "2025-01-01", "2025-12-31", 2, 0)), List.of());
        assertTrue(cells(result).stream().allMatch(c -> "仅期间任务".equals(c.get("state"))));
        assertNull(result.get("carbon"));
        assertEquals(new BigDecimal("0.0"), result.get("coveragePercent"));
    }
    @Test void incompleteFailedMissingAndCompleteAreSeparate() {
        Map<String, Object> result = build(List.of(task(4, "2025-03-01", "2025-03-31", 3, 1),
                task(3, "2025-02-01", "2025-02-28", 2, 1), task(2, "2025-01-01", "2025-01-31", 2, 0)), List.of());
        assertEquals("完整", cells(result).get(0).get("state"));
        assertEquals("质量待核对", cells(result).get(1).get("state"));
        assertEquals("核算失败", cells(result).get(2).get("state"));
        assertEquals("无月度任务", cells(result).get(3).get("state"));
        assertEquals(new BigDecimal("8.3"), result.get("coveragePercent"));
        assertEquals(2L, result.get("problemTaskCount"));
    }
    @Test void realZeroIsNotMissingAndUnitsStaySeparate() {
        Map<String, Object> row = Map.of("carbon", BigDecimal.ZERO, "energies", List.of(
            Map.of("unitName", "MWh", "subcategoryName", "电力", "energy", new BigDecimal("10"), "carbon", BigDecimal.ZERO),
            Map.of("unitName", "GJ", "subcategoryName", "热力", "energy", new BigDecimal("20"), "carbon", BigDecimal.ZERO)));
        Map<String, Object> result = build(List.of(), List.of(row));
        assertEquals(BigDecimal.ZERO, result.get("carbon"));
        assertEquals(Map.of("MWh", new BigDecimal("10"), "GJ", new BigDecimal("20")), result.get("units"));
    }
    @Test void validatesCompanyAndYearBeforeLoadingFacts() {
        AnalysisMapper facts = mock(AnalysisMapper.class);
        ManagementDashboardMapper management = mock(ManagementDashboardMapper.class);
        when(management.selectCompanies()).thenReturn(List.of(Map.of("id", 3030L)));
        when(management.selectYears()).thenReturn(List.of(2025));
        ManagementDashboardService service = new ManagementDashboardService(facts, management);
        assertThrows(RuntimeException.class, () -> service.dashboard(2025, 999L));
        assertThrows(RuntimeException.class, () -> service.dashboard(1000, null));
        verifyNoInteractions(facts);
    }
    @Test void excludesFailedAndQualityFlaggedTasksFromFactLoader() {
        AnalysisMapper facts = mock(AnalysisMapper.class);
        ManagementDashboardMapper management = mock(ManagementDashboardMapper.class);
        when(management.selectCompanies()).thenReturn(List.of(Map.of("id", 3030L, "name", "机辆")));
        when(management.selectYears()).thenReturn(List.of(2025));
        when(management.selectTasks("2025-01-01", "2025-12-31", null)).thenReturn(List.of(task(7, "2025-01-01", "2025-12-31", 2, 1)));
        when(facts.selectNodes(anyString(), anyString())).thenReturn(List.of());
        when(facts.selectFacts(anyString(), anyString())).thenReturn(List.of());
        when(facts.selectDirectFacts(anyString(), anyString())).thenReturn(List.of());
        assertNull(new ManagementDashboardService(facts, management).dashboard(2025, null).get("carbon"));
    }
    @Test void onlyApprovedFormalTaskIdsEnterTotalsAndPartialMonthsAreNotExpanded() {
        AnalysisMapper facts = mock(AnalysisMapper.class);
        ManagementDashboardMapper management = mock(ManagementDashboardMapper.class);
        when(management.selectCompanies()).thenReturn(List.of(Map.of("id", 3030L, "name", "机辆")));
        when(management.selectYears()).thenReturn(List.of(2025));
        when(management.selectTasks("2025-01-01", "2025-12-31", null)).thenReturn(List.of(task(7, "2025-01-01", "2025-12-31", 2, 0)));
        AnalysisFact good = fact(7L, "2025-01-01", "2025-12-31", "8");
        when(facts.selectNodes(anyString(), anyString())).thenReturn(List.of());
        when(facts.selectFacts(anyString(), anyString())).thenReturn(List.of(good, fact(502L, "2025-01-01", "2025-12-31", "9000")));
        when(facts.selectDirectFacts(anyString(), anyString())).thenReturn(List.of());
        ManagementDashboardService service = new ManagementDashboardService(facts, management);
        assertEquals(new BigDecimal("8"), service.dashboard(2025, null).get("carbon"));
        good.setCycleStart("2025-01-05"); good.setCycleEnd("2025-01-20");
        Map<String, Object> partial = service.dashboard(2025, null);
        assertNull(partial.get("carbon")); assertEquals(List.of(), partial.get("monthlyRows"));
    }
    private AnalysisFact fact(Long task, String start, String end, String carbon) {
        AnalysisFact f = new AnalysisFact();
        f.setTemplateId(task); f.setSourceNodeId(1L); f.setCalcNodeId(task); f.setNodeName("机辆"); f.setNodeCategory("BRANCH");
        f.setCycleStart(start); f.setCycleEnd(end); f.setCalculationEndTime("2026-10-26 10:00:00");
        f.setCarbonValue(new BigDecimal(carbon)); f.setEnergyValue(BigDecimal.ONE); f.setUnitName("MWh"); f.setUnitCode("MWh"); f.setSubcategory("PE_PF"); f.setSubcategoryName("电力");
        return f;
    }
}
