package com.ruoyi.carbon.analysis.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.analysis.service.AnalysisService.LoadedFacts;

/**
 * 把统计分析同一套成功核算，收成大屏预览要用的数字。没有对应字段的图保持为空。
 */
@Service
public class ScreenDashboardService
{
    private static final BigDecimal ZERO = BigDecimal.ZERO;
    private static final LocalDate RANGE_START = LocalDate.of(2000, 1, 1);
    private static final LocalDate RANGE_END = LocalDate.of(2099, 12, 31);
    private static final List<String> MONTH_LABELS = List.of("1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月");

    private final AnalysisService analysisService;

    public ScreenDashboardService(AnalysisService analysisService)
    {
        this.analysisService = analysisService;
    }

    public Map<String, Object> dashboard()
    {
        LoadedFacts loaded = analysisService.loadFacts(RANGE_START, RANGE_END);
        List<Map<String, Object>> branchYears = rows(analysisService.queryFacts(loaded, "year", RANGE_START, RANGE_END, "BRANCH", "total"));
        List<Map<String, Object>> stationYears = rows(analysisService.queryFacts(loaded, "year", RANGE_START, RANGE_END, "STATION", "total"));
        List<Map<String, Object>> branchMonths = rows(analysisService.queryFacts(loaded, "month", RANGE_START, RANGE_END, "BRANCH", "total"));
        List<Map<String, Object>> stationMonths = rows(analysisService.queryFacts(loaded, "month", RANGE_START, RANGE_END, "STATION", "total"));
        List<Map<String, Object>> branchCategories = rows(analysisService.queryFacts(loaded, "year", RANGE_START, RANGE_END, "BRANCH", "category"));
        List<Map<String, Object>> stationCategories = rows(analysisService.queryFacts(loaded, "year", RANGE_START, RANGE_END, "STATION", "category"));
        int year = latestYear(branchYears, stationYears);
        if (year == 0) return emptyDashboard();
        return build(year, branchYears, stationYears, branchMonths, stationMonths, branchCategories, stationCategories,
                analysisService.categoryNames());
    }

    static Map<String, Object> build(int year, List<Map<String, Object>> branchYears, List<Map<String, Object>> stationYears,
            List<Map<String, Object>> branchMonths, List<Map<String, Object>> stationMonths,
            List<Map<String, Object>> branchCategories, List<Map<String, Object>> stationCategories)
    {
        return build(year, branchYears, stationYears, branchMonths, stationMonths, branchCategories, stationCategories, Map.of());
    }

    static Map<String, Object> build(int year, List<Map<String, Object>> branchYears, List<Map<String, Object>> stationYears,
            List<Map<String, Object>> branchMonths, List<Map<String, Object>> stationMonths,
            List<Map<String, Object>> branchCategories, List<Map<String, Object>> stationCategories,
            Map<String, String> categoryNames)
    {
        List<Map<String, Object>> branchYearRows = inYear(branchYears, year);
        List<Map<String, Object>> previousBranchRows = inYear(branchYears, year - 1);
        List<Map<String, Object>> stationYearRows = inYear(stationYears, year);
        List<Map<String, Object>> previousStationRows = inYear(stationYears, year - 1);
        boolean useStationRollup = sumCarbon(branchYearRows).signum() == 0
                && sumCarbon(stationYearRows).signum() != 0;
        List<Map<String, Object>> overallYears = useStationRollup ? stationYearRows : branchYearRows;
        List<Map<String, Object>> previousOverallYears = useStationRollup ? previousStationRows : previousBranchRows;
        List<Map<String, Object>> overallMonths = useStationRollup ? stationMonths : branchMonths;
        List<Map<String, Object>> overallCategories = useStationRollup ? stationCategories : branchCategories;
        Map<String, BigDecimal> branchMonthTotals = monthTotals(overallMonths, null);
        YearMonth latestMonth = latestMonthInYear(branchMonthTotals, year);
        Map<String, Object> dashboard = new LinkedHashMap<>();
        dashboard.put("periodLabel", periodLabel(year, latestMonth));
        dashboard.put("unit", "tCO2e");
        dashboard.put("overall", bucket(sumCarbon(overallYears), monthCarbon(branchMonthTotals, latestMonth),
                yoy(sumCarbon(overallYears), sumCarbon(previousOverallYears)), stationYearRows.size(),
                line(branchMonthTotals, latestMonth), surface(overallMonths, null),
                pies(inYear(overallCategories, year), categoryNames)));
        Map<String, Object> stations = new LinkedHashMap<>();
        Map<Long, String> names = stationNames(stationYears, stationMonths);
        for (Map.Entry<Long, String> station : names.entrySet())
        {
            Long orgId = station.getKey();
            List<Map<String, Object>> ownYear = forOrg(stationYearRows, orgId);
            Map<String, BigDecimal> ownMonths = monthTotals(stationMonths, orgId);
            YearMonth ownLatest = latestMonthInYear(ownMonths, year);
            stations.put(station.getValue(), bucket(sumCarbon(ownYear), monthCarbon(ownMonths, ownLatest),
                    yoy(sumCarbon(ownYear), sumCarbon(forOrg(inYear(stationYears, year - 1), orgId))), 0,
                    line(ownMonths, ownLatest), surface(stationMonths, orgId),
                    pies(forOrg(inYear(stationCategories, year), orgId), categoryNames)));
        }
        dashboard.put("stations", stations);
        Map<String, Object> mapEmissions = new LinkedHashMap<>();
        for (Map<String, Object> row : stationYearRows)
        {
            Map<String, Object> point = new LinkedHashMap<>();
            point.put("carbonEmission", number(carbon(row)));
            point.put("carbonIntensity", 0);
            mapEmissions.put(text(row.get("orgName")), point);
        }
        dashboard.put("mapEmissions", mapEmissions);
        List<List<String>> rank = new ArrayList<>();
        List<Map<String, Object>> ranked = new ArrayList<>(stationYearRows);
        ranked.sort(Comparator.comparing((Map<String, Object> row) -> carbon(row)).reversed()
                .thenComparing(row -> text(row.get("orgName"))));
        for (Map<String, Object> row : ranked)
        {
            rank.add(List.of(text(row.get("orgName")), carbonText(carbon(row)), "0"));
        }
        dashboard.put("rank", rank);
        return dashboard;
    }

    static Map<String, Object> emptyDashboard()
    {
        Map<String, Object> dashboard = new LinkedHashMap<>();
        dashboard.put("periodLabel", "统计周期：");
        dashboard.put("unit", "tCO2e");
        dashboard.put("overall", bucket(ZERO, ZERO, ZERO, 0, List.of(), emptySurface(), emptyPies()));
        dashboard.put("stations", new LinkedHashMap<>());
        dashboard.put("mapEmissions", new LinkedHashMap<>());
        dashboard.put("rank", List.of());
        return dashboard;
    }

    private static Map<String, Object> bucket(BigDecimal yearTotal, BigDecimal monthTotal, BigDecimal yoy, int pointCount,
            List<Map<String, Object>> lineSource, Map<String, Object> surface, Map<String, Object> pies)
    {
        Map<String, Object> kpi = new LinkedHashMap<>();
        kpi.put("yearTotal", number(yearTotal));
        kpi.put("monthTotal", number(monthTotal));
        kpi.put("yoyPercent", yoy.doubleValue());
        kpi.put("pointCount", pointCount);
        kpi.put("intensity", 0);
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("dimensions", List.of("month", "actual", "forecast"));
        line.put("source", lineSource);
        Map<String, Object> bucket = new LinkedHashMap<>();
        bucket.put("kpi", kpi);
        bucket.put("line", line);
        bucket.put("surface", surface);
        bucket.put("pies", pies);
        return bucket;
    }

    private static List<Map<String, Object>> line(Map<String, BigDecimal> totals, YearMonth latest)
    {
        List<Map<String, Object>> source = new ArrayList<>();
        if (latest == null) return source;
        for (int i = 11; i >= 0; i--)
        {
            YearMonth month = latest.minusMonths(i);
            String key = month.toString();
            Map<String, Object> point = new LinkedHashMap<>();
            point.put("month", key);
            point.put("actual", totals.containsKey(key) ? number(totals.get(key)) : null);
            point.put("forecast", null);
            source.add(point);
        }
        return source;
    }

    private static Map<String, Object> surface(List<Map<String, Object>> monthRows, Long orgId)
    {
        Map<Integer, BigDecimal[]> byYear = new TreeMap<>();
        for (Map<String, Object> row : monthRows)
        {
            if (orgId != null && orgId(row) != orgId) continue;
            YearMonth month = monthOf(row);
            if (month == null) continue;
            BigDecimal[] values = byYear.computeIfAbsent(month.getYear(), key -> new BigDecimal[12]);
            int index = month.getMonthValue() - 1;
            values[index] = (values[index] == null ? ZERO : values[index]).add(carbon(row));
        }
        List<Integer> years = new ArrayList<>(byYear.keySet());
        List<List<Double>> values = new ArrayList<>();
        for (Integer surfaceYear : years)
        {
            List<Double> row = new ArrayList<>();
            BigDecimal[] months = byYear.get(surfaceYear);
            for (int i = 0; i < 12; i++) row.add(months[i] == null ? 0d : number(months[i]));
            values.add(row);
        }
        Map<String, Object> surface = emptySurface();
        surface.put("years", years);
        surface.put("values", values);
        return surface;
    }

    private static Map<String, Object> emptySurface()
    {
        Map<String, Object> surface = new LinkedHashMap<>();
        surface.put("timeType", "month");
        surface.put("years", List.of());
        surface.put("times", MONTH_LABELS);
        surface.put("values", List.of());
        surface.put("unit", "tCO2e");
        return surface;
    }

    private static Map<String, Object> pies(List<Map<String, Object>> categoryRows, Map<String, String> categoryNames)
    {
        Map<String, BigDecimal> bySource = new LinkedHashMap<>();
        Map<String, BigDecimal> byScene = new LinkedHashMap<>();
        Map<String, BigDecimal> bySegment = new LinkedHashMap<>();
        for (Map<String, Object> row : categoryRows)
        {
            for (Map<String, Object> energy : energies(row))
            {
                String name = text(energy.get("subcategoryName"));
                if (name.isEmpty()) name = text(energy.get("subcategory"));
                if (name.isEmpty()) name = "未命名";
                bySource.merge(name, carbon(energy), BigDecimal::add);
                String scene = categoryLabel(energy.get("categoryL1"), categoryNames);
                if (!scene.isEmpty()) byScene.merge(scene, carbon(energy), BigDecimal::add);
                String segment = categoryLabel(energy.get("categoryL2"), categoryNames);
                if (!segment.isEmpty()) bySegment.merge(segment, carbon(energy), BigDecimal::add);
            }
        }
        Map<String, Object> pies = emptyPies();
        putSlices(pies, "source", bySource);
        putSlices(pies, "type", byScene);
        putSlices(pies, "segment", bySegment);
        return pies;
    }

    private static String categoryLabel(Object raw, Map<String, String> categoryNames)
    {
        String code = text(raw);
        if (code.isEmpty() || categoryNames == null) return code;
        String name = categoryNames.get(code);
        return name == null || name.isBlank() ? code : name;
    }

    @SuppressWarnings("unchecked")
    private static void putSlices(Map<String, Object> pies, String kind, Map<String, BigDecimal> totals)
    {
        List<Map<String, Object>> source = new ArrayList<>();
        for (Map.Entry<String, BigDecimal> entry : totals.entrySet())
        {
            Map<String, Object> slice = new LinkedHashMap<>();
            slice.put("name", entry.getKey());
            slice.put("value", number(entry.getValue()));
            source.add(slice);
        }
        source.sort(Comparator.comparing((Map<String, Object> slice) -> new BigDecimal(String.valueOf(slice.get("value")))).reversed());
        ((Map<String, Object>) pies.get(kind)).put("source", source);
    }

    private static Map<String, Object> emptyPies()
    {
        Map<String, Object> pies = new LinkedHashMap<>();
        pies.put("source", pie(List.of()));
        pies.put("type", pie(List.of()));
        pies.put("segment", pie(List.of()));
        return pies;
    }

    private static Map<String, Object> pie(List<Map<String, Object>> source)
    {
        Map<String, Object> pie = new LinkedHashMap<>();
        pie.put("dimensions", List.of("name", "value"));
        pie.put("source", source);
        return pie;
    }

    private static String periodLabel(int year, YearMonth latest)
    {
        if (latest == null) return "统计周期：" + year + "年";
        YearMonth start = latest.minusMonths(11);
        return "统计周期：" + start.getYear() + "年" + start.getMonthValue() + "月—" + latest.getYear() + "年" + latest.getMonthValue() + "月";
    }

    private static int latestYear(List<Map<String, Object>> branchYears, List<Map<String, Object>> stationYears)
    {
        int year = 0;
        for (List<Map<String, Object>> rows : List.of(branchYears, stationYears))
        {
            for (Map<String, Object> row : rows)
            {
                String period = text(row.get("period"));
                if (period.length() != 4) continue;
                year = Math.max(year, Integer.parseInt(period));
            }
        }
        return year;
    }

    private static List<Map<String, Object>> inYear(List<Map<String, Object>> rows, int year)
    {
        String key = String.valueOf(year);
        List<Map<String, Object>> kept = new ArrayList<>();
        for (Map<String, Object> row : rows)
        {
            if (key.equals(text(row.get("period")))) kept.add(row);
        }
        return kept;
    }

    private static Map<String, BigDecimal> monthTotals(List<Map<String, Object>> rows, Long orgId)
    {
        Map<String, BigDecimal> totals = new LinkedHashMap<>();
        for (Map<String, Object> row : rows)
        {
            if (orgId != null && orgId(row) != orgId) continue;
            YearMonth month = monthOf(row);
            if (month == null) continue;
            totals.merge(month.toString(), carbon(row), BigDecimal::add);
        }
        return totals;
    }

    private static YearMonth latestMonthInYear(Map<String, BigDecimal> totals, int year)
    {
        YearMonth latest = null;
        String prefix = year + "-";
        for (String key : totals.keySet())
        {
            if (!key.startsWith(prefix)) continue;
            YearMonth month = YearMonth.parse(key);
            if (latest == null || month.isAfter(latest)) latest = month;
        }
        return latest;
    }

    private static BigDecimal monthCarbon(Map<String, BigDecimal> totals, YearMonth month)
    {
        if (month == null) return ZERO;
        return totals.getOrDefault(month.toString(), ZERO);
    }

    private static BigDecimal yoy(BigDecimal current, BigDecimal previous)
    {
        if (previous == null || previous.signum() == 0) return ZERO.setScale(1, RoundingMode.HALF_UP);
        return current.subtract(previous).multiply(new BigDecimal("100")).divide(previous, 1, RoundingMode.HALF_UP);
    }

    private static Map<Long, String> stationNames(List<Map<String, Object>> stationYears, List<Map<String, Object>> stationMonths)
    {
        Map<Long, String> names = new LinkedHashMap<>();
        for (List<Map<String, Object>> rows : List.of(stationYears, stationMonths))
        {
            for (Map<String, Object> row : rows)
            {
                long id = orgId(row);
                if (id == 0) continue;
                names.putIfAbsent(id, text(row.get("orgName")));
            }
        }
        return names;
    }

    private static List<Map<String, Object>> forOrg(List<Map<String, Object>> rows, long orgId)
    {
        List<Map<String, Object>> kept = new ArrayList<>();
        for (Map<String, Object> row : rows)
        {
            if (orgId(row) == orgId) kept.add(row);
        }
        return kept;
    }

    private static BigDecimal sumCarbon(List<Map<String, Object>> rows)
    {
        BigDecimal total = ZERO;
        for (Map<String, Object> row : rows) total = total.add(carbon(row));
        return total;
    }

    private static YearMonth monthOf(Map<String, Object> row)
    {
        String period = text(row.get("period"));
        if (period.length() != 7) return null;
        return YearMonth.parse(period);
    }

    private static long orgId(Map<String, Object> row)
    {
        Object value = row.get("orgId");
        if (value instanceof Number) return ((Number) value).longValue();
        if (value == null || String.valueOf(value).isBlank()) return 0L;
        return Long.parseLong(String.valueOf(value));
    }

    private static BigDecimal carbon(Map<String, Object> row)
    {
        Object value = row.get("carbon");
        if (value == null) return ZERO;
        if (value instanceof BigDecimal) return (BigDecimal) value;
        return new BigDecimal(String.valueOf(value));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> energies(Map<String, Object> row)
    {
        Object value = row.get("energies");
        if (!(value instanceof List<?>)) return List.of();
        return (List<Map<String, Object>>) value;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rows(Map<String, Object> query)
    {
        Object value = query.get("rows");
        if (!(value instanceof List<?>)) return List.of();
        return (List<Map<String, Object>>) value;
    }

    private static double number(BigDecimal value)
    {
        return value.setScale(3, RoundingMode.HALF_UP).doubleValue();
    }

    private static String carbonText(BigDecimal value)
    {
        return value.setScale(3, RoundingMode.HALF_UP).stripTrailingZeros().toPlainString();
    }

    private static String text(Object value)
    {
        return value == null ? "" : String.valueOf(value);
    }
}
