package com.ruoyi.carbon.analysis.service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;
import com.ruoyi.carbon.analysis.domain.AnalysisNode;
import com.ruoyi.carbon.analysis.mapper.AnalysisMapper;
import com.ruoyi.carbon.analysis.mapper.ManagementDashboardMapper;
import com.ruoyi.common.core.exception.ServiceException;

/** Independent management screen: original calculation snapshots, no estimation or factor replacement. */
@Service
public class ManagementDashboardService {
    private final AnalysisMapper facts;
    private final ManagementDashboardMapper management;
    private final AnalysisAggregator aggregator = new AnalysisAggregator();

    public ManagementDashboardService(AnalysisMapper facts, ManagementDashboardMapper management) {
        this.facts = facts; this.management = management;
    }

    public Map<String, Object> dashboard(Integer requestedYear, Long companyId) {
        List<Map<String, Object>> companies = management.selectCompanies();
        if (companyId != null && companies.stream().noneMatch(c -> number(c, "id") == companyId))
            throw new ServiceException("请选择有效的正式核算公司");
        List<Integer> years = management.selectYears();
        int year = requestedYear == null ? (years.isEmpty() ? LocalDate.now().getYear() : years.get(0)) : requestedYear;
        if (year < 2000 || year > 2100) throw new ServiceException("年份应在2000至2100之间");
        if (!years.contains(year)) { years = new ArrayList<>(years); years.add(year); }
        String start = year + "-01-01", end = year + "-12-31";
        List<Map<String, Object>> tasks = management.selectTasks(start, end, companyId);
        Set<Long> allowed = tasks.stream().filter(ManagementDashboardService::usable)
                .map(t -> number(t, "id")).collect(Collectors.toSet());
        List<AnalysisNode> nodes = facts.selectNodes(start, end).stream()
                .filter(n -> allowed.contains(n.getTemplateId())).collect(Collectors.toList());
        List<AnalysisFact> values = facts.selectFacts(start, end).stream()
                .filter(f -> allowed.contains(f.getTemplateId())).collect(Collectors.toCollection(ArrayList::new));
        Set<Long> summarized = values.stream().map(AnalysisFact::getTemplateId).collect(Collectors.toSet());
        for (AnalysisFact f : facts.selectDirectFacts(start, end))
            if (allowed.contains(f.getTemplateId()) && !summarized.contains(f.getTemplateId())) values.add(f);
        // The legacy aggregator also labels partial months MONTH; this screen promises full natural months.
        List<AnalysisFact> calendarValues = values.stream().filter(ManagementDashboardService::calendarPeriod).collect(Collectors.toList());
        Map<String, Object> annual = aggregator.query(nodes, calendarValues, "year", LocalDate.parse(start), LocalDate.parse(end), "BRANCH", null, "category", null, null);
        Map<String, Object> monthly = aggregator.query(nodes, calendarValues, "month", LocalDate.parse(start), LocalDate.parse(end), "BRANCH", null, "category", null, null);
        return build(year, companies, years, companyId, tasks, rows(annual), rows(monthly));
    }

    static Map<String, Object> build(int year, List<Map<String, Object>> companies, List<Integer> years,
            Long companyId, List<Map<String, Object>> tasks, List<Map<String, Object>> annual, List<Map<String, Object>> monthly) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("year", year); out.put("companies", companies); out.put("years", years);
        out.put("companyId", companyId); out.put("unit", "tCO₂e");
        out.put("basis", "原核算冻结因子；按源节点及周期取最新合格成功任务。月度与年度独立取数，未统一因子重算，可能不相等。");
        out.put("annualRows", annual); out.put("monthlyRows", monthly);
        Map<String, BigDecimal> units = new LinkedHashMap<>(), sources = new LinkedHashMap<>();
        BigDecimal carbon = null;
        for (Map<String, Object> row : annual) {
            if (row.get("carbon") != null) carbon = (carbon == null ? BigDecimal.ZERO : carbon).add(decimal(row.get("carbon")));
            for (Map<String, Object> energy : energies(row)) {
                String unit = text(energy, "unitName");
                if (energy.get("energy") != null) units.merge(unit, decimal(energy.get("energy")), BigDecimal::add);
                if (energy.get("carbon") != null) sources.merge(text(energy, "subcategoryName"), decimal(energy.get("carbon")), BigDecimal::add);
            }
        }
        out.put("carbon", carbon); out.put("units", units); out.put("sources", sources);
        List<Map<String, Object>> coverage = new ArrayList<>();
        int complete = 0, expected = 0;
        List<String> problems = new ArrayList<>();
        for (Map<String, Object> company : companies) {
            long id = number(company, "id");
            if (companyId != null && id != companyId) continue;
            List<Map<String, Object>> cells = new ArrayList<>();
            for (int m = 1; m <= 12; m++) {
                LocalDate first = LocalDate.of(year, m, 1), last = first.withDayOfMonth(first.lengthOfMonth());
                Map<String, Object> selected = tasks.stream().filter(t -> number(t, "companyId") == id)
                        .filter(t -> first.toString().equals(text(t, "start")) && last.toString().equals(text(t, "end")))
                        .findFirst().orElse(null);
                Map<String, Object> wider = tasks.stream().filter(t -> number(t, "companyId") == id
                        && text(t, "start").compareTo(first.toString()) <= 0 && text(t, "end").compareTo(last.toString()) >= 0).findFirst().orElse(null);
                String state = selected == null ? (wider != null ? "仅期间任务" : "无月度任务") : quality(selected);
                if ("完整".equals(state)) complete++;
                expected++;
                Map<String, Object> cell = new LinkedHashMap<>();
                cell.put("month", m); cell.put("state", state);
                cell.put("taskId", selected != null ? selected.get("id") : wider == null ? null : wider.get("id"));
                cell.put("description", selected != null ? detail(selected) : wider == null
                        ? "没有精确覆盖该自然月的任务；不分摊期间总量"
                        : "仅有" + text(wider, "start") + "至" + text(wider, "end") + "的期间任务，" + detail(wider) + "；不分摊到单月");
                cells.add(cell);
            }
            coverage.add(Map.of("company", company.get("name"), "cells", cells));
        }
        for (Map<String, Object> t : tasks) {
            if (!usable(t) && problems.size() < 30)
                problems.add(text(t, "companyName") + " · 任务" + t.get("id") + " · " + text(t, "start") + "至" + text(t, "end") + " · " + detail(t));
        }
        if (annual.isEmpty()) problems.add("本期没有可展示的正式分公司汇总；请核对成功任务、明细质量和模型组织分类。");
        if (monthly.isEmpty()) problems.add("暂无可展示的月度核算结果；年度及跨月结果不会拆分到各月。");
        out.put("coverage", coverage);
        out.put("coveragePercent", expected == 0 ? null : BigDecimal.valueOf(100.0 * complete / expected).setScale(1, java.math.RoundingMode.HALF_UP));
        out.put("coverageLabel", "完整自然月任务覆盖率：" + complete + "/" + expected + "（所选公司×12个月，含尚未到达月份；非采集完整率）");
        out.put("problemTaskCount", tasks.stream().filter(t -> !usable(t)).count());
        out.put("problems", problems);
        out.put("recent", tasks.stream().limit(8).map(t -> List.of(text(t, "companyName"), String.valueOf(t.get("id")), text(t, "start") + "至" + text(t, "end"), quality(t), text(t, "completed"))).collect(Collectors.toList()));
        out.put("updatedAt", tasks.stream().map(t -> text(t, "completed")).filter(s -> !s.isEmpty()).max(String::compareTo).orElse("暂无核算记录"));
        return out;
    }

    private static String quality(Map<String, Object> task) {
        if (number(task, "status") != 2) return number(task, "status") == 3 ? "核算失败" : "待完成";
        if (number(task, "dataCount") == 0) return "无明细";
        if (number(task, "problemCount") > 0) return "质量待核对";
        if (number(task, "factorMissingCount") > 0) return "因子快照缺失";
        return "完整";
    }
    private static String detail(Map<String, Object> task) {
        return quality(task) + "；异常明细" + number(task, "problemCount") + "条，因子或排放快照缺失" + number(task, "factorMissingCount") + "条";
    }
    private static boolean usable(Map<String, Object> task) { return "完整".equals(quality(task)); }
    private static boolean calendarPeriod(AnalysisFact fact) {
        if (fact.getCycleStart() == null || fact.getCycleEnd() == null) return false;
        LocalDate start = LocalDate.parse(fact.getCycleStart()), end = LocalDate.parse(fact.getCycleEnd());
        if (start.getDayOfMonth() != 1) return false;
        return end.equals(start.plusMonths(1).minusDays(1))
                || (start.getMonthValue() == 1 && end.equals(start.plusYears(1).minusDays(1)))
                || ((start.getMonthValue() - 1) % 3 == 0 && end.equals(start.plusMonths(3).minusDays(1)));
    }
    private static long number(Map<String, Object> m, String key) { return m.get(key) instanceof Number ? ((Number)m.get(key)).longValue() : 0; }
    private static String text(Map<String, Object> m, String key) { return m.get(key) == null ? "" : m.get(key).toString(); }
    private static BigDecimal decimal(Object value) { return value == null ? BigDecimal.ZERO : new BigDecimal(value.toString()); }
    @SuppressWarnings("unchecked") private static List<Map<String, Object>> rows(Map<String, Object> result) { return (List<Map<String, Object>>)result.get("rows"); }
    @SuppressWarnings("unchecked") private static List<Map<String, Object>> energies(Map<String, Object> row) { return (List<Map<String, Object>>)row.getOrDefault("energies", List.of()); }
}
