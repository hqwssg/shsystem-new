package com.ruoyi.carbon.report.source;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;

/**
 * Expands accepted collection points into monthly activity rows.
 * These rows are not added to the cycle activity that chapter 5 recalculates.
 */
public final class ReportMonthlyActivityBuilder
{
    public record Series(List<Map<String, Object>> fuels, List<Map<String, Object>> electricity)
    {
        public static Series empty()
        {
            return new Series(List.of(), List.of());
        }
    }

    private ReportMonthlyActivityBuilder()
    {
    }

    public static Series load(EmissionCalculationMapper mapper, ReportTask task)
    {
        if (mapper == null || task == null || task.getCalculationTemplateId() == null || task.getReportYear() == null)
        {
            return Series.empty();
        }
        List<CalculationNodeDataRow> accepted = acceptedPoints(mapper, task);
        if (accepted.isEmpty())
        {
            return Series.empty();
        }
        CalculationCandidate source = mapper.selectTask(task.getCalculationTemplateId());
        LocalDate cycleStart = source == null ? null : toLocal(source.getCycleStart());
        LocalDate cycleEnd = source == null ? null : toLocal(source.getCycleEnd());
        List<YearMonth> covered = coveredMonths(task.getPeriodType(), task.getReportYear(), task.getReportMonth(),
                cycleStart, cycleEnd);
        if (covered.isEmpty())
        {
            return Series.empty();
        }
        YearMonth first = covered.get(0);
        YearMonth last = covered.get(covered.size() - 1);
        List<MonthlyCollectionActivityRow> stored = mapper.selectMonthlyCollectionBetween(
                first.getYear(), first.getMonthValue(), last.getYear(), last.getMonthValue(),
                ids(accepted, 1), ids(accepted, 2), ids(accepted, 3));
        Set<YearMonth> allowed = new LinkedHashSet<>(covered);
        List<MonthlyCollectionActivityRow> inWindow = new ArrayList<>();
        if (stored != null)
        {
            for (MonthlyCollectionActivityRow row : stored)
            {
                if (row.getYear() != null && row.getMonth() != null
                        && allowed.contains(YearMonth.of(row.getYear(), row.getMonth())))
                {
                    inWindow.add(row);
                }
            }
        }
        Set<Integer> monthNumbers = new LinkedHashSet<>();
        for (YearMonth month : covered)
        {
            monthNumbers.add(month.getMonthValue());
        }
        return build(accepted, inWindow, new ReportUnitConverter(), monthNumbers);
    }

    public static List<CalculationNodeDataRow> acceptedPoints(EmissionCalculationMapper mapper, ReportTask task)
    {
        JSONObject saved = ReportSourceSnapshot.saved(task);
        if (saved == null || task.getCalculationTemplateId() == null)
        {
            return List.of();
        }
        Set<Long> sourceIds = new LinkedHashSet<>();
        collectSourceIds(saved.getJSONArray("fuels"), sourceIds);
        collectSourceIds(saved.getJSONArray("electricity"), sourceIds);
        collectSourceIds(saved.getJSONArray("heat"), sourceIds);
        if (sourceIds.isEmpty())
        {
            return List.of();
        }
        List<CalculationNodeDataRow> rows = mapper.selectNodeData(task.getCalculationTemplateId());
        if (rows == null)
        {
            return List.of();
        }
        List<CalculationNodeDataRow> accepted = new ArrayList<>();
        for (CalculationNodeDataRow row : rows)
        {
            if (row.getId() != null && sourceIds.contains(row.getId())
                    && row.getCollectionPointId() != null && row.getCollectionPointType() != null)
            {
                accepted.add(row);
            }
        }
        return accepted;
    }

    public static Series build(List<CalculationNodeDataRow> accepted, List<MonthlyCollectionActivityRow> monthly,
            ReportUnitConverter converter, Set<Integer> months)
    {
        Map<String, CalculationNodeDataRow> points = new LinkedHashMap<>();
        for (CalculationNodeDataRow row : accepted)
        {
            if (row.getCollectionPointType() == null || row.getCollectionPointId() == null)
            {
                continue;
            }
            points.putIfAbsent(key(row.getCollectionPointType(), row.getCollectionPointId()), row);
        }
        List<Map<String, Object>> fuels = new ArrayList<>();
        List<Map<String, Object>> electricity = new ArrayList<>();
        for (MonthlyCollectionActivityRow row : monthly)
        {
            if (row.getMonth() == null || !months.contains(row.getMonth()) || Integer.valueOf(2).equals(row.getDataStatus()))
            {
                continue;
            }
            CalculationNodeDataRow point = points.get(key(row.getCollectionPointType(), row.getCollectionPointId()));
            if (point == null)
            {
                continue;
            }
            String code = ActivityClassifier.canonical(point.getEmissionSubcategory(), point.getMeasurementUnit());
            String bucket = ActivityClassifier.bucket(code);
            ReportUnitConverter.Conversion conversion = converter.convert(code, row.preferredEnergyValue(), row.getMeasurementUnit());
            if (!conversion.ok || conversion.normalizedValue == null)
            {
                continue;
            }
            String sourceName = point.getFacilityName() == null || point.getFacilityName().isBlank()
                    ? "采集点" : point.getFacilityName();
            if ("fuel".equals(bucket))
            {
                String fuelType = ReportUnitConverter.reportFuelType(code);
                if (fuelType == null)
                {
                    continue;
                }
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("fuel_type", fuelType);
                item.put("facility", point.getFacilityName() == null ? "" : point.getFacilityName());
                item.put("quantity", conversion.normalizedValue);
                item.put("unit", conversion.normalizedUnit);
                item.put("month", row.getMonth());
                if (row.getYear() != null)
                {
                    item.put("year", row.getYear());
                }
                item.put("source_name", sourceName);
                fuels.add(item);
            }
            else if ("electricity".equals(bucket))
            {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("scope", "purchased-electricity");
                item.put("quantity_mwh", conversion.normalizedValue);
                item.put("month", row.getMonth());
                if (row.getYear() != null)
                {
                    item.put("year", row.getYear());
                }
                item.put("source_name", sourceName);
                electricity.add(item);
            }
        }
        return new Series(fuels, electricity);
    }

    public static List<YearMonth> coveredMonths(String periodType, Integer reportYear, Integer reportMonth,
            LocalDate cycleStart, LocalDate cycleEnd)
    {
        if (reportYear == null || cycleStart == null || cycleEnd == null || cycleEnd.isBefore(cycleStart))
        {
            return List.of();
        }
        if ("MONTH".equalsIgnoreCase(periodType))
        {
            return months(periodType, reportYear, reportMonth, cycleStart, cycleEnd).stream()
                    .map(month -> YearMonth.of(reportYear, month)).toList();
        }
        if (cycleStart.getYear() == cycleEnd.getYear())
        {
            return months(periodType, reportYear, reportMonth, cycleStart, cycleEnd).stream()
                    .map(month -> YearMonth.of(reportYear, month)).toList();
        }
        List<YearMonth> result = new ArrayList<>();
        YearMonth last = YearMonth.from(cycleEnd);
        for (YearMonth cursor = YearMonth.from(cycleStart); !cursor.isAfter(last); cursor = cursor.plusMonths(1))
        {
            result.add(cursor);
        }
        return result;
    }

    public static List<Integer> months(String periodType, Integer reportYear, Integer reportMonth,
            LocalDate cycleStart, LocalDate cycleEnd)
    {
        if (reportYear == null || cycleStart == null || cycleEnd == null || cycleEnd.isBefore(cycleStart))
        {
            return List.of();
        }
        if ("MONTH".equalsIgnoreCase(periodType))
        {
            if (reportMonth == null || reportMonth < 1 || reportMonth > 12)
            {
                return List.of();
            }
            LocalDate start = LocalDate.of(reportYear, reportMonth, 1);
            LocalDate end = start.withDayOfMonth(start.lengthOfMonth());
            if (end.isBefore(cycleStart) || start.isAfter(cycleEnd))
            {
                return List.of();
            }
            return List.of(reportMonth);
        }
        if (cycleEnd.getYear() < reportYear || cycleStart.getYear() > reportYear)
        {
            return List.of();
        }
        int from = cycleStart.getYear() < reportYear ? 1 : cycleStart.getMonthValue();
        int to = cycleEnd.getYear() > reportYear ? 12 : cycleEnd.getMonthValue();
        List<Integer> result = new ArrayList<>();
        for (int month = from; month <= to; month++)
        {
            result.add(month);
        }
        return result;
    }

    public static LocalDate toLocal(Date value)
    {
        if (value == null)
        {
            return null;
        }
        if (value instanceof java.sql.Date sql)
        {
            return sql.toLocalDate();
        }
        return value.toInstant().atZone(ZoneId.systemDefault()).toLocalDate();
    }

    private static void collectSourceIds(JSONArray lines, Set<Long> sourceIds)
    {
        if (lines == null)
        {
            return;
        }
        for (int index = 0; index < lines.size(); index++)
        {
            JSONObject line = lines.getJSONObject(index);
            if (line == null || line.getString("sourceId") == null || line.getString("sourceId").isBlank())
            {
                continue;
            }
            try
            {
                sourceIds.add(Long.valueOf(line.getString("sourceId")));
            }
            catch (NumberFormatException ignored)
            {
                // A manual row without a calculation id cannot be joined to a collection point.
            }
        }
    }

    private static List<Long> ids(List<CalculationNodeDataRow> rows, int type)
    {
        return rows.stream().filter(row -> Integer.valueOf(type).equals(row.getCollectionPointType()))
                .map(CalculationNodeDataRow::getCollectionPointId).distinct().toList();
    }

    private static String key(Integer type, Long id)
    {
        return type + ":" + id;
    }

    public static BigDecimal carbonOf(MonthlyCollectionActivityRow row)
    {
        return row == null ? null : row.preferredCarbonValue();
    }
}
