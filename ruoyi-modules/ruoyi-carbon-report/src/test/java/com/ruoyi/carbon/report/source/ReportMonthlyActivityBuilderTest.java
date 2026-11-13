package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import org.mockito.Answers;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.generation.ReportSnapshotAssembler;

class ReportMonthlyActivityBuilderTest
{
    @Test
    void monthlySeriesUsesAdjustedValueAndSkipsMissingMonths()
    {
        CalculationNodeDataRow gas = point(1L, 2, 9L, "天然气", "m3", "canteen");
        CalculationNodeDataRow diesel = point(2L, 2, 8L, "柴油", "t", "vehicle");
        MonthlyCollectionActivityRow january = month(2, 9L, 1, "10000", "12000", 1);
        MonthlyCollectionActivityRow missing = month(2, 9L, 2, "1", "1", 2);
        MonthlyCollectionActivityRow dieselMonth = month(2, 8L, 1, "3", null, 1);
        MonthlyCollectionActivityRow outsider = month(2, 7L, 1, "9", "9", 1);
        ReportMonthlyActivityBuilder.Series series = ReportMonthlyActivityBuilder.build(
                List.of(gas, diesel), List.of(january, missing, dieselMonth, outsider),
                new ReportUnitConverter(), Set.of(1, 2, 3));
        assertEquals(2, series.fuels().size());
        assertEquals(0, new BigDecimal("1.200000").compareTo((BigDecimal) series.fuels().get(0).get("quantity")));
        assertEquals("10k_m3", series.fuels().get(0).get("unit"));
        assertEquals(1, series.fuels().get(0).get("month"));
        assertEquals("natural_gas", series.fuels().get(0).get("fuel_type"));
        assertEquals("diesel", series.fuels().get(1).get("fuel_type"));
        assertEquals("vehicle", series.fuels().get(1).get("facility"));
        assertEquals(0, new BigDecimal("3").compareTo((BigDecimal) series.fuels().get(1).get("quantity")));
        assertTrue(series.electricity().isEmpty());
    }

    @Test
    void yearWindowStaysInsideTheCalculationCycle()
    {
        List<Integer> months = ReportMonthlyActivityBuilder.months("YEAR", 2025, null,
                LocalDate.of(2025, 3, 1), LocalDate.of(2025, 9, 30));
        assertEquals(List.of(3, 4, 5, 6, 7, 8, 9), months);
        assertEquals(List.of(3), ReportMonthlyActivityBuilder.months("MONTH", 2025, 3,
                LocalDate.of(2025, 3, 1), LocalDate.of(2025, 9, 30)));
        assertTrue(ReportMonthlyActivityBuilder.months("MONTH", 2025, 1,
                LocalDate.of(2025, 3, 1), LocalDate.of(2025, 9, 30)).isEmpty());
    }

    @Test
    void crossYearCycleKeepsEveryMonthThroughTheEndYear()
    {
        List<YearMonth> covered = ReportMonthlyActivityBuilder.coveredMonths("RANGE", 2026, null,
                LocalDate.of(2025, 1, 1), LocalDate.of(2026, 5, 31));
        assertEquals(17, covered.size());
        assertEquals(YearMonth.of(2025, 1), covered.get(0));
        assertEquals(YearMonth.of(2025, 12), covered.get(11));
        assertEquals(YearMonth.of(2026, 5), covered.get(16));
        assertEquals(List.of(YearMonth.of(2025, 11), YearMonth.of(2025, 12), YearMonth.of(2026, 1), YearMonth.of(2026, 2)),
                ReportMonthlyActivityBuilder.coveredMonths("RANGE", 2026, null,
                        LocalDate.of(2025, 11, 15), LocalDate.of(2026, 2, 10)));
        assertEquals(List.of(YearMonth.of(2025, 3), YearMonth.of(2025, 4), YearMonth.of(2025, 5),
                YearMonth.of(2025, 6), YearMonth.of(2025, 7), YearMonth.of(2025, 8), YearMonth.of(2025, 9)),
                ReportMonthlyActivityBuilder.coveredMonths("YEAR", 2025, null,
                        LocalDate.of(2025, 3, 1), LocalDate.of(2025, 9, 30)));
    }

    @Test
    void crossYearLoadReadsMonthsFromBothYears()
    {
        EmissionCalculationMapper mapper = mock(EmissionCalculationMapper.class, Answers.CALLS_REAL_METHODS);
        CalculationCandidate source = new CalculationCandidate();
        source.setCycleStart(java.sql.Date.valueOf(LocalDate.of(2025, 1, 1)));
        source.setCycleEnd(java.sql.Date.valueOf(LocalDate.of(2026, 5, 31)));
        when(mapper.selectTask(900016006L)).thenReturn(source);
        when(mapper.selectAttributionTables()).thenReturn(Set.of());
        when(mapper.selectNodeDataCompatible(eq(900016006L), any())).thenReturn(List.of(
                point(11L, 2, 91002L, "柴油", "t", "肃宁柴油计量表")));
        MonthlyCollectionActivityRow december = month(2, 91002L, 12, "1", null, 1);
        december.setYear(2025);
        MonthlyCollectionActivityRow may = month(2, 91002L, 5, "2", null, 1);
        may.setYear(2026);
        MonthlyCollectionActivityRow afterCycle = month(2, 91002L, 6, "9", null, 1);
        afterCycle.setYear(2026);
        when(mapper.selectMonthlyCollectionBetween(eq(2025), eq(1), eq(2026), eq(5), any(), any(), any()))
                .thenReturn(List.of(december, may, afterCycle));
        ReportTask task = new ReportTask();
        task.setCalculationTemplateId(900016006L);
        task.setReportYear(2026);
        task.setPeriodType("RANGE");
        task.setMetadataJson("{\"_source_snapshot\":{\"fuels\":[{\"sourceId\":\"11\"}]}}");
        ReportMonthlyActivityBuilder.Series series = ReportMonthlyActivityBuilder.load(mapper, task);
        assertEquals(2, series.fuels().size());
        assertEquals(2025, series.fuels().get(0).get("year"));
        assertEquals(12, series.fuels().get(0).get("month"));
        assertEquals(2026, series.fuels().get(1).get("year"));
        assertEquals(5, series.fuels().get(1).get("month"));
    }

    @Test
    void snapshotKeepsCycleActivitySeparateFromMonthlyRows()
    {
        ReportTask task = new ReportTask();
        task.setTitle("合成测试");
        task.setReportYear(2025);
        task.setPeriodType("YEAR");
        task.setMetadataJson("{}");
        task.setEntityProfileJson("{\"short_name\":\"合成\",\"business_description\":\"测试\",\"carbon_department\":\"测试\"}");
        ReportActivityRow fuel = new ReportActivityRow();
        fuel.setFuelType("natural_gas");
        fuel.setFacility("canteen");
        fuel.setNormalizedValue(new BigDecimal("8"));
        fuel.setNormalizedUnit("10k_m3");
        fuel.setSourceName("周期合计");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getFuels().add(fuel);
        String json = new ReportSnapshotAssembler().assemble(draft, new ReportDeptProfile(), null,
                List.of(java.util.Map.of("fuel_type", "natural_gas", "facility", "canteen",
                        "quantity", new BigDecimal("1.2"), "unit", "10k_m3", "month", 1, "source_name", "月度")),
                List.of());
        JSONObject snapshot = JSON.parseObject(json);
        assertEquals(1, snapshot.getJSONArray("fuel_activity").size());
        assertEquals(8, snapshot.getJSONArray("fuel_activity").getJSONObject(0).getIntValue("quantity"));
        assertEquals(1, snapshot.getJSONArray("monthly_fuel_activity").size());
        assertEquals(1, snapshot.getJSONArray("monthly_fuel_activity").getJSONObject(0).getIntValue("month"));
        assertTrue(snapshot.getJSONArray("monthly_electricity_activity").isEmpty());
    }

    private static CalculationNodeDataRow point(long id, int type, long pointId, String subcategory, String unit, String facility)
    {
        CalculationNodeDataRow row = new CalculationNodeDataRow();
        row.setId(id);
        row.setCollectionPointType(type);
        row.setCollectionPointId(pointId);
        row.setEmissionSubcategory(subcategory);
        row.setMeasurementUnit(unit);
        row.setFacilityName(facility);
        row.setDataStatus(1);
        return row;
    }

    private static MonthlyCollectionActivityRow month(int type, long pointId, int month, String raw, String adjusted, int status)
    {
        MonthlyCollectionActivityRow row = new MonthlyCollectionActivityRow();
        row.setCollectionPointType(type);
        row.setCollectionPointId(pointId);
        row.setYear(2025);
        row.setMonth(month);
        row.setMeasurementUnit(type == 2 && pointId == 9L ? "m3" : "t");
        row.setEnergyMeasurementValue(new BigDecimal(raw));
        row.setAdjustedEnergyValue(adjusted == null ? null : new BigDecimal(adjusted));
        row.setDataStatus(status);
        return row;
    }
}
