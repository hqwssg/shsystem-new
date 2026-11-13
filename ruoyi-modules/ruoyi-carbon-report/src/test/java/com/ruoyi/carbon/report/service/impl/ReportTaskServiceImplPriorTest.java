package com.ruoyi.carbon.report.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import java.math.BigDecimal;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptSubjectMapper;

class ReportTaskServiceImplPriorTest
{
    @Test
    void monthlyLookupIgnoresYearLongCalculation()
    {
        ReportTask task = monthTask(2025, 3);
        EmissionCalculationMapper calcMapper = mock(EmissionCalculationMapper.class);
        ReportDeptSubjectMapper subjectMapper = mock(ReportDeptSubjectMapper.class);
        when(subjectMapper.selectByDeptId(301L)).thenReturn(subject());
        CalculationCandidate yearLong = candidate(1L, date(2024, 1, 1), date(2024, 12, 31));
        when(calcMapper.selectCandidates(eq(1001L), any(Date.class), any(Date.class)))
                .thenReturn(List.of(yearLong));
        ReportTaskServiceImpl service = service(calcMapper, subjectMapper);
        assertNull(service.lookupPriorYear(task));
    }

    @Test
    void monthlyLookupUsesContainedMonthAndJanuaryMomIsPreviousDecember()
    {
        ReportTask task = monthTask(2025, 1);
        EmissionCalculationMapper calcMapper = mock(EmissionCalculationMapper.class);
        ReportDeptSubjectMapper subjectMapper = mock(ReportDeptSubjectMapper.class);
        when(subjectMapper.selectByDeptId(301L)).thenReturn(subject());
        CalculationCandidate yoy = candidate(11L, date(2024, 1, 1), date(2024, 1, 31));
        CalculationCandidate mom = candidate(12L, date(2024, 12, 1), date(2024, 12, 31));
        when(calcMapper.selectCandidates(eq(1001L), any(Date.class), any(Date.class)))
                .thenAnswer(invocation -> {
                    Date start = invocation.getArgument(1);
                    Calendar calendar = Calendar.getInstance();
                    calendar.setTime(start);
                    if (calendar.get(Calendar.MONTH) == Calendar.JANUARY)
                    {
                        return List.of(yoy);
                    }
                    return List.of(mom);
                });
        when(calcMapper.selectNodeData(11L, "主体")).thenReturn(List.of(row("燃料", "4")));
        when(calcMapper.selectNodeData(12L, "主体")).thenReturn(List.of(row("燃料", "5")));
        ReportTaskServiceImpl service = service(calcMapper, subjectMapper);
        JSONObject json = JSON.parseObject(service.lookupPriorYear(task));
        assertEquals(2024, json.getJSONObject("yoy").getIntValue("report_year"));
        assertEquals(1, json.getJSONObject("yoy").getIntValue("report_month"));
        assertEquals(0, new BigDecimal("4").compareTo(json.getJSONObject("yoy").getBigDecimal("total_emissions_tco2")));
        assertEquals(2024, json.getJSONObject("mom").getIntValue("report_year"));
        assertEquals(12, json.getJSONObject("mom").getIntValue("report_month"));
        assertEquals(0, new BigDecimal("5").compareTo(json.getJSONObject("mom").getBigDecimal("total_emissions_tco2")));
    }

    @Test
    void monthlyComparisonUsesCollectionMonthCarbonBeforeCalculationTasks()
    {
        ReportTask task = monthTask(2025, 3);
        task.setCalculationTemplateId(77L);
        task.setMetadataJson("{\"_source_snapshot\":{\"fuels\":[{\"sourceId\":\"5\"}]}}");
        EmissionCalculationMapper calcMapper = mock(EmissionCalculationMapper.class);
        ReportDeptSubjectMapper subjectMapper = mock(ReportDeptSubjectMapper.class);
        when(subjectMapper.selectByDeptId(301L)).thenReturn(subject());
        CalculationNodeDataRow point = new CalculationNodeDataRow();
        point.setId(5L);
        point.setCollectionPointType(2);
        point.setCollectionPointId(90L);
        when(calcMapper.selectNodeData(77L)).thenReturn(List.of(point));
        com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow month = new com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow();
        month.setEmissionCategory("燃料");
        month.setDataStatus(1);
        month.setAdjustedEnergyValue(new BigDecimal("1"));
        month.setAdjustedCarbonEmission(new BigDecimal("6.5"));
        when(calcMapper.selectMonthlyCollection(eq(2024), eq(3), eq(3), any(), any(), any())).thenReturn(List.of(month));
        ReportTaskServiceImpl service = service(calcMapper, subjectMapper);
        JSONObject json = JSON.parseObject(service.lookupPriorYear(task));
        assertEquals(0, new BigDecimal("6.5").compareTo(json.getJSONObject("yoy").getBigDecimal("total_emissions_tco2")));
        assertEquals(0, new BigDecimal("6.5").compareTo(json.getJSONObject("yoy").getBigDecimal("fuel_combustion_tco2")));
    }

    @Test
    void missingMonthlyRowsFallBackToContainedCalculation()
    {
        assertNull(ReportTaskServiceImpl.totalsFromMonthly(List.of()));
        com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow empty = new com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow();
        empty.setDataStatus(2);
        empty.setAdjustedCarbonEmission(new BigDecimal("9"));
        assertNull(ReportTaskServiceImpl.totalsFromMonthly(List.of(empty)));
    }

    @Test
    void firstContainedSkipsYearCycleInsideMonthWindow()
    {
        Date[] march = ReportTaskServiceImpl.monthRange(2024, 3);
        CalculationCandidate yearLong = candidate(1L, date(2024, 1, 1), date(2024, 12, 31));
        CalculationCandidate month = candidate(2L, date(2024, 3, 1), date(2024, 3, 31));
        assertEquals(2L, ReportTaskServiceImpl.firstContained(List.of(yearLong, month), march[0], march[1]).getId());
        assertNull(ReportTaskServiceImpl.firstContained(List.of(yearLong), march[0], march[1]));
    }

    @Test
    void monthlyStaleAnnualJsonNeedsRelookup()
    {
        ReportTask task = monthTask(2025, 3);
        task.setPriorYearJson("{\"report_year\":2024,\"total_emissions_tco2\":1000}");
        assertTrue(ReportTaskServiceImpl.needsPriorLookup(task));
        task.setPriorYearJson("{\"yoy\":{\"report_year\":2024,\"report_month\":3,\"total_emissions_tco2\":1}}");
        assertFalse(ReportTaskServiceImpl.needsPriorLookup(task));
    }

    private static ReportTaskServiceImpl service(EmissionCalculationMapper calcMapper, ReportDeptSubjectMapper subjectMapper)
    {
        ReportTaskServiceImpl service = new ReportTaskServiceImpl();
        ReflectionTestUtils.setField(service, "emissionCalculationMapper", calcMapper);
        ReflectionTestUtils.setField(service, "reportDeptSubjectMapper", subjectMapper);
        return service;
    }

    private static ReportTask monthTask(int year, int month)
    {
        ReportTask task = new ReportTask();
        task.setDeptId(301L);
        task.setPeriodType("MONTH");
        task.setReportYear(year);
        task.setReportMonth(month);
        return task;
    }

    private static ReportDeptSubject subject()
    {
        ReportDeptSubject subject = new ReportDeptSubject();
        subject.setDeptId(301L);
        subject.setSubjectNodeId(1001L);
        subject.setEnergyAllocation("主体");
        return subject;
    }

    private static CalculationCandidate candidate(Long id, Date start, Date end)
    {
        CalculationCandidate row = new CalculationCandidate();
        row.setId(id);
        row.setCycleStart(start);
        row.setCycleEnd(end);
        return row;
    }

    private static CalculationNodeDataRow row(String category, String value)
    {
        CalculationNodeDataRow data = new CalculationNodeDataRow();
        data.setEmissionCategory(category);
        data.setCarbonEmission(new BigDecimal(value));
        return data;
    }

    private static Date date(int year, int month, int day)
    {
        Calendar calendar = Calendar.getInstance();
        calendar.clear();
        calendar.set(year, month - 1, day);
        return calendar.getTime();
    }
}
