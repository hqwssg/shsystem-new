package com.ruoyi.carbon.analysis.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;
import com.ruoyi.carbon.analysis.domain.AnalysisNode;

/**
 * 把成功核算的节点汇总归到月、季、年。同一节点同一周期只保留最晚结束的一次核算。
 */
public class AnalysisAggregator
{
    private static final BigDecimal ZERO = BigDecimal.ZERO;

    public Map<String, Object> query(List<AnalysisNode> nodes, List<AnalysisFact> facts, String grain,
            LocalDate start, LocalDate end, String orgLevel, Long parentNodeId, String categoryMode,
            String energyCategory, String subcategory)
    {
        Map<Long, AnalysisNode> nodesById = indexNodes(nodes);
        List<AnalysisFact> scoped = new ArrayList<>();
        for (AnalysisFact fact : facts)
        {
            if (fact == null || fact.getSourceNodeId() == null) continue;
            if (!orgLevel.equals(fact.getNodeCategory())) continue;
            if (!underParent(fact.getCalcNodeId(), parentNodeId, nodesById)) continue;
            scoped.add(fact);
        }
        Map<String, Winner> winners = winners(scoped);
        List<String> periods = periodsOverlapping(grain, start, end);
        List<Picked> picked = pick(scoped, winners, grain, periods);
        List<Picked> visible = new ArrayList<>();
        for (Picked item : picked)
        {
            if (matchesCategory(item.fact, energyCategory, subcategory)) visible.add(item);
        }
        boolean byCategory = "category".equals(categoryMode);
        List<Map<String, Object>> rows = aggregate(visible, byCategory);
        rows.sort(Comparator.comparing((Map<String, Object> row) -> String.valueOf(row.get("period")))
                .thenComparing(row -> String.valueOf(row.get("orgName"))));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("grain", grain);
        result.put("periods", periods);
        result.put("notices", notices(grain, scoped, winners, picked));
        result.put("rows", rows);
        result.put("chartType", distinctOrgs(rows).size() > 1 ? "bar" : "line");
        result.put("chartMetric", chartMetric(rows));
        result.put("unitName", singleUnitName(rows));
        return result;
    }

    public Map<String, Object> compare(Map<String, Object> current, Map<String, Object> previous, boolean yearOnYear)
    {
        List<Map<String, Object>> currentRows = rowsOf(current);
        List<Map<String, Object>> previousRows = rowsOf(previous);
        Map<Long, Map<String, Object>> previousByOrg = new LinkedHashMap<>();
        for (Map<String, Object> row : previousRows) previousByOrg.put(longValue(row.get("orgId")), row);
        Set<Long> orgIds = new LinkedHashSet<>();
        for (Map<String, Object> row : currentRows) orgIds.add(longValue(row.get("orgId")));
        if (yearOnYear)
        {
            for (Map<String, Object> row : previousRows) orgIds.add(longValue(row.get("orgId")));
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Long orgId : orgIds)
        {
            Map<String, Object> now = findOrg(currentRows, orgId);
            Map<String, Object> then = yearOnYear ? previousByOrg.get(orgId) : null;
            rows.add(mergeOrg(orgId, now, then, yearOnYear));
        }
        rows.sort(Comparator.comparing(row -> String.valueOf(row.get("orgName"))));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("compareType", yearOnYear ? "yoy" : "org");
        result.put("notices", mergeNotices(current, previous));
        result.put("rows", rows);
        result.put("chartType", "bar");
        result.put("chartMetric", chartMetric(yearOnYear ? currentRows : rows));
        result.put("unitName", singleUnitName(currentRows.isEmpty() ? previousRows : currentRows));
        return result;
    }

    private Map<String, Object> mergeOrg(Long orgId, Map<String, Object> now, Map<String, Object> then, boolean yearOnYear)
    {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("orgId", orgId);
        row.put("orgName", nameOf(now, then));
        BigDecimal currentCarbon = now == null ? null : decimal(now.get("carbon"));
        BigDecimal previousCarbon = then == null ? null : decimal(then.get("carbon"));
        row.put("currentCarbon", currentCarbon);
        if (yearOnYear)
        {
            row.put("previousCarbon", previousCarbon);
            row.put("carbonDelta", delta(currentCarbon, previousCarbon));
            row.put("carbonRate", rate(currentCarbon, previousCarbon));
        }
        row.put("energies", mergeEnergies(energiesOf(now), energiesOf(then), yearOnYear));
        return row;
    }

    private List<Map<String, Object>> mergeEnergies(List<Map<String, Object>> current, List<Map<String, Object>> previous,
            boolean yearOnYear)
    {
        Map<String, Map<String, Object>> previousByKey = new LinkedHashMap<>();
        for (Map<String, Object> item : previous) previousByKey.put(energyKey(item), item);
        Set<String> keys = new LinkedHashSet<>();
        for (Map<String, Object> item : current) keys.add(energyKey(item));
        if (yearOnYear)
        {
            keys.addAll(previousByKey.keySet());
        }
        List<Map<String, Object>> merged = new ArrayList<>();
        for (String key : keys)
        {
            Map<String, Object> now = findEnergy(current, key);
            Map<String, Object> then = yearOnYear ? previousByKey.get(key) : null;
            Map<String, Object> source = now != null ? now : then;
            Map<String, Object> line = new LinkedHashMap<>();
            line.put("subcategory", source.get("subcategory"));
            line.put("subcategoryName", source.get("subcategoryName"));
            line.put("unitCode", source.get("unitCode"));
            line.put("unitName", source.get("unitName"));
            BigDecimal currentEnergy = now == null ? null : decimal(now.get("energy"));
            BigDecimal previousEnergy = then == null ? null : decimal(then.get("energy"));
            line.put("current", currentEnergy);
            line.put("carbon", now == null ? null : decimal(now.get("carbon")));
            if (yearOnYear)
            {
                line.put("previous", previousEnergy);
                line.put("delta", delta(currentEnergy, previousEnergy));
                line.put("rate", rate(currentEnergy, previousEnergy));
            }
            merged.add(line);
        }
        return merged;
    }

    private List<String> notices(String grain, List<AnalysisFact> scoped, Map<String, Winner> winners, List<Picked> picked)
    {
        List<String> notices = new ArrayList<>();
        boolean irregular = false;
        boolean coarserThanMonth = false;
        boolean widerThanQuarter = false;
        boolean quarterOnlyYear = false;
        boolean incomplete = false;
        Set<String> quarterMonths = new LinkedHashSet<>();
        Set<String> yearMonths = new LinkedHashSet<>();
        Set<String> quarterFilled = new LinkedHashSet<>();
        Set<String> yearFilled = new LinkedHashSet<>();
        for (AnalysisFact fact : scoped)
        {
            String span = span(fact);
            if ("OTHER".equals(span)) irregular = true;
            if ("month".equals(grain) && ("QUARTER".equals(span) || "YEAR".equals(span))) coarserThanMonth = true;
            if ("quarter".equals(grain) && "YEAR".equals(span)) widerThanQuarter = true;
            if ("year".equals(grain) && "QUARTER".equals(span) && isWinner(fact, winners))
            {
                String year = String.valueOf(date(fact.getCycleStart()).getYear());
                if (!hasYearOrMonth(scoped, winners, fact.getSourceNodeId(), year)) quarterOnlyYear = true;
            }
        }
        for (Picked item : picked)
        {
            if (!"MONTH".equals(span(item.fact))) continue;
            String month = periodKey("MONTH", date(item.fact.getCycleStart()));
            if ("quarter".equals(grain))
            {
                quarterMonths.add(item.fact.getSourceNodeId() + "|" + item.period + "|" + month);
                quarterFilled.add(item.fact.getSourceNodeId() + "|" + item.period);
            }
            if ("year".equals(grain))
            {
                yearMonths.add(item.fact.getSourceNodeId() + "|" + item.period + "|" + month);
                yearFilled.add(item.fact.getSourceNodeId() + "|" + item.period);
            }
        }
        for (String key : quarterFilled)
        {
            int count = 0;
            for (String mark : quarterMonths)
            {
                if (mark.startsWith(key + "|")) count++;
            }
            if (count > 0 && count < 3) incomplete = true;
        }
        for (String key : yearFilled)
        {
            int count = 0;
            for (String mark : yearMonths)
            {
                if (mark.startsWith(key + "|")) count++;
            }
            if (count > 0 && count < 12) incomplete = true;
        }
        if ("month".equals(grain) && (irregular || coarserThanMonth))
        {
            notices.add("有核算周期跨月，不能拆进单月，这些核算未计入。");
        }
        if ("quarter".equals(grain) && (irregular || widerThanQuarter))
        {
            notices.add("有跨季核算，不能拆进单季，这些核算未计入。");
        }
        if ("year".equals(grain) && irregular)
        {
            notices.add("有未覆盖整年的核算，未计入年度合计。");
        }
        if (quarterOnlyYear)
        {
            notices.add("部分组织只有季度核算，没有月数据或年度核算，年度合计未包含它们。");
        }
        if (incomplete)
        {
            notices.add("部分合计由月数据相加，缺少的月份没有计入。");
        }
        return notices;
    }

    private boolean hasYearOrMonth(List<AnalysisFact> scoped, Map<String, Winner> winners, Long sourceNodeId, String year)
    {
        for (AnalysisFact fact : scoped)
        {
            if (!sourceNodeId.equals(fact.getSourceNodeId()) || !isWinner(fact, winners)) continue;
            String span = span(fact);
            LocalDate start = date(fact.getCycleStart());
            if (start == null || start.getYear() != Integer.parseInt(year)) continue;
            if ("YEAR".equals(span) || "MONTH".equals(span)) return true;
        }
        return false;
    }

    private List<Picked> pick(List<AnalysisFact> scoped, Map<String, Winner> winners, String grain, List<String> periods)
    {
        Set<String> periodSet = new LinkedHashSet<>(periods);
        Map<String, Set<Long>> direct = new LinkedHashMap<>();
        if ("quarter".equals(grain) || "year".equals(grain))
        {
            String directSpan = "quarter".equals(grain) ? "QUARTER" : "YEAR";
            for (AnalysisFact fact : scoped)
            {
                if (!directSpan.equals(span(fact)) || !isWinner(fact, winners)) continue;
                String label = periodKey(directSpan, date(fact.getCycleStart()));
                if (!periodSet.contains(label)) continue;
                direct.computeIfAbsent(label, key -> new LinkedHashSet<>()).add(fact.getSourceNodeId());
            }
        }
        List<Picked> picked = new ArrayList<>();
        for (AnalysisFact fact : scoped)
        {
            if (!isWinner(fact, winners)) continue;
            String span = span(fact);
            LocalDate start = date(fact.getCycleStart());
            if ("month".equals(grain) && "MONTH".equals(span))
            {
                String label = periodKey(span, start);
                if (periodSet.contains(label)) picked.add(new Picked(fact, label));
            }
            else if ("quarter".equals(grain) && "QUARTER".equals(span))
            {
                String label = periodKey(span, start);
                if (periodSet.contains(label)) picked.add(new Picked(fact, label));
            }
            else if ("year".equals(grain) && "YEAR".equals(span))
            {
                String label = periodKey(span, start);
                if (periodSet.contains(label)) picked.add(new Picked(fact, label));
            }
            else if ("MONTH".equals(span) && ("quarter".equals(grain) || "year".equals(grain)))
            {
                String label = "quarter".equals(grain) ? quarterKey(start) : String.valueOf(start.getYear());
                if (!periodSet.contains(label)) continue;
                Set<Long> covered = direct.getOrDefault(label, Set.of());
                if (!covered.contains(fact.getSourceNodeId())) picked.add(new Picked(fact, label));
            }
        }
        return picked;
    }

    private List<Map<String, Object>> aggregate(List<Picked> picked, boolean byCategory)
    {
        Map<String, Bucket> buckets = new LinkedHashMap<>();
        for (Picked item : picked)
        {
            AnalysisFact fact = item.fact;
            String bucketKey = fact.getSourceNodeId() + "|" + item.period;
            Bucket bucket = buckets.computeIfAbsent(bucketKey, key -> new Bucket(fact.getSourceNodeId(), fact.getNodeName(), item.period));
            bucket.carbon = bucket.carbon.add(value(fact.getCarbonValue()));
            String unitCode = blank(fact.getUnitCode()) ? "未填单位" : fact.getUnitCode();
            String energyKey = byCategory
                    ? text(fact.getSubcategory()) + "|" + unitCode + "|" + text(fact.getEnergyCategoryL1()) + "|"
                            + text(fact.getEnergyCategoryL2()) + "|" + text(fact.getEnergyCategoryL3())
                    : unitCode;
            Energy energy = bucket.energies.computeIfAbsent(energyKey, key -> new Energy());
            energy.subcategory = byCategory ? fact.getSubcategory() : null;
            energy.subcategoryName = byCategory ? fact.getSubcategoryName() : null;
            if (byCategory && energy.categoryL1 == null && energy.categoryL2 == null && energy.categoryL3 == null)
            {
                energy.categoryL1 = fact.getEnergyCategoryL1();
                energy.categoryL2 = fact.getEnergyCategoryL2();
                energy.categoryL3 = fact.getEnergyCategoryL3();
            }
            energy.unitCode = unitCode;
            energy.unitName = blank(fact.getUnitName()) ? unitCode : fact.getUnitName();
            energy.energy = energy.energy.add(value(fact.getEnergyValue()));
            energy.carbon = energy.carbon.add(value(fact.getCarbonValue()));
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Bucket bucket : buckets.values())
        {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("orgId", bucket.orgId);
            row.put("orgName", bucket.orgName);
            row.put("period", bucket.period);
            row.put("carbon", bucket.carbon);
            List<Map<String, Object>> energies = new ArrayList<>();
            for (Energy energy : bucket.energies.values())
            {
                Map<String, Object> line = new LinkedHashMap<>();
                line.put("subcategory", energy.subcategory);
                line.put("subcategoryName", energy.subcategoryName);
                line.put("categoryL1", energy.categoryL1);
                line.put("categoryL2", energy.categoryL2);
                line.put("categoryL3", energy.categoryL3);
                line.put("unitCode", energy.unitCode);
                line.put("unitName", energy.unitName);
                line.put("energy", energy.energy);
                line.put("carbon", energy.carbon);
                energies.add(line);
            }
            row.put("energies", energies);
            rows.add(row);
        }
        return rows;
    }

    private Map<String, Winner> winners(List<AnalysisFact> facts)
    {
        Map<String, Winner> winners = new LinkedHashMap<>();
        for (AnalysisFact fact : facts)
        {
            String span = span(fact);
            if ("OTHER".equals(span) || fact.getSourceNodeId() == null || fact.getTemplateId() == null) continue;
            String key = fact.getSourceNodeId() + "|" + span + "|" + periodKey(span, date(fact.getCycleStart()));
            Winner current = winners.get(key);
            String endTime = fact.getCalculationEndTime() == null ? "" : fact.getCalculationEndTime();
            if (current == null || endTime.compareTo(current.endTime) > 0
                    || (endTime.equals(current.endTime) && fact.getTemplateId() > current.templateId))
            {
                winners.put(key, new Winner(fact.getTemplateId(), endTime));
            }
        }
        return winners;
    }

    private boolean isWinner(AnalysisFact fact, Map<String, Winner> winners)
    {
        String span = span(fact);
        if ("OTHER".equals(span) || fact.getTemplateId() == null) return false;
        Winner winner = winners.get(fact.getSourceNodeId() + "|" + span + "|" + periodKey(span, date(fact.getCycleStart())));
        return winner != null && winner.templateId == fact.getTemplateId();
    }

    static String span(AnalysisFact fact)
    {
        LocalDate start = date(fact.getCycleStart());
        LocalDate end = date(fact.getCycleEnd());
        if (start == null || end == null || end.isBefore(start)) return "OTHER";
        if (start.getYear() == end.getYear() && start.getMonth() == end.getMonth()) return "MONTH";
        if (exactQuarter(start, end)) return "QUARTER";
        if (start.getDayOfMonth() == 1 && start.getMonthValue() == 1 && end.getMonthValue() == 12
                && end.getDayOfMonth() == 31 && start.getYear() == end.getYear())
        {
            return "YEAR";
        }
        return "OTHER";
    }

    private static boolean exactQuarter(LocalDate start, LocalDate end)
    {
        int month = start.getMonthValue();
        if (start.getDayOfMonth() != 1 || (month != 1 && month != 4 && month != 7 && month != 10)) return false;
        return end.equals(start.plusMonths(3).minusDays(1));
    }

    static String periodKey(String span, LocalDate start)
    {
        if ("MONTH".equals(span)) return monthKey(start);
        if ("QUARTER".equals(span)) return quarterKey(start);
        return String.valueOf(start.getYear());
    }

    static List<String> periodsOverlapping(String grain, LocalDate start, LocalDate end)
    {
        List<String> periods = new ArrayList<>();
        if ("month".equals(grain))
        {
            YearMonth cursor = YearMonth.from(start);
            YearMonth last = YearMonth.from(end);
            while (!cursor.isAfter(last))
            {
                periods.add(monthKey(cursor.atDay(1)));
                cursor = cursor.plusMonths(1);
            }
        }
        else if ("quarter".equals(grain))
        {
            LocalDate cursor = quarterStart(start);
            LocalDate last = quarterStart(end);
            while (!cursor.isAfter(last))
            {
                periods.add(quarterKey(cursor));
                cursor = cursor.plusMonths(3);
            }
        }
        else
        {
            for (int year = start.getYear(); year <= end.getYear(); year++) periods.add(String.valueOf(year));
        }
        return periods;
    }

    private static LocalDate quarterStart(LocalDate date)
    {
        int month = ((date.getMonthValue() - 1) / 3) * 3 + 1;
        return LocalDate.of(date.getYear(), month, 1);
    }

    private static String monthKey(LocalDate date)
    {
        return String.format("%d-%02d", date.getYear(), date.getMonthValue());
    }

    private static String quarterKey(LocalDate date)
    {
        return date.getYear() + "-Q" + (((date.getMonthValue() - 1) / 3) + 1);
    }

    private boolean underParent(Long calcNodeId, Long parentNodeId, Map<Long, AnalysisNode> nodesById)
    {
        if (parentNodeId == null) return true;
        AnalysisNode node = nodesById.get(calcNodeId);
        if (node == null) return false;
        Long current = parentId(node.getParentCalcNodeId());
        Set<Long> seen = new LinkedHashSet<>();
        while (current != null && seen.add(current))
        {
            AnalysisNode ancestor = nodesById.get(current);
            if (ancestor == null) return false;
            if (parentNodeId.equals(ancestor.getSourceNodeId())) return true;
            current = parentId(ancestor.getParentCalcNodeId());
        }
        return false;
    }

    private boolean matchesCategory(AnalysisFact fact, String energyCategory, String subcategory)
    {
        if (!blank(subcategory) && !subcategory.equals(fact.getSubcategory())) return false;
        if (blank(energyCategory)) return true;
        return energyCategory.equals(fact.getEnergyCategoryL1())
                || energyCategory.equals(fact.getEnergyCategoryL2())
                || energyCategory.equals(fact.getEnergyCategoryL3());
    }

    private Map<Long, AnalysisNode> indexNodes(List<AnalysisNode> nodes)
    {
        Map<Long, AnalysisNode> indexed = new LinkedHashMap<>();
        if (nodes == null) return indexed;
        for (AnalysisNode node : nodes)
        {
            if (node != null && node.getCalcNodeId() != null) indexed.put(node.getCalcNodeId(), node);
        }
        return indexed;
    }

    private static Long parentId(Long parentCalcNodeId)
    {
        if (parentCalcNodeId == null || parentCalcNodeId == 0L) return null;
        return parentCalcNodeId;
    }

    private static LocalDate date(String text)
    {
        if (blank(text) || text.length() < 10) return null;
        return LocalDate.parse(text.substring(0, 10));
    }

    private static boolean blank(String text)
    {
        return text == null || text.isBlank();
    }

    private static String text(String value)
    {
        return value == null ? "" : value;
    }

    private static BigDecimal value(BigDecimal number)
    {
        return number == null ? ZERO : number;
    }

    private static String chartMetric(List<Map<String, Object>> rows)
    {
        return singleUnitName(rows) == null ? "carbon" : "energy";
    }

    private static String singleUnitName(List<Map<String, Object>> rows)
    {
        String unitName = null;
        int lines = 0;
        for (Map<String, Object> row : rows)
        {
            List<Map<String, Object>> energies = energiesOf(row);
            lines += energies.size();
            for (Map<String, Object> energy : energies)
            {
                String name = String.valueOf(energy.get("unitName"));
                if (unitName == null) unitName = name;
                else if (!unitName.equals(name)) return null;
            }
        }
        return lines == 0 ? null : unitName;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rowsOf(Map<String, Object> result)
    {
        Object rows = result == null ? null : result.get("rows");
        return rows instanceof List ? (List<Map<String, Object>>) rows : List.of();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> energiesOf(Map<String, Object> row)
    {
        if (row == null) return List.of();
        Object energies = row.get("energies");
        return energies instanceof List ? (List<Map<String, Object>>) energies : List.of();
    }

    private static List<String> mergeNotices(Map<String, Object> current, Map<String, Object> previous)
    {
        Set<String> notices = new LinkedHashSet<>();
        addNotices(notices, current);
        addNotices(notices, previous);
        return new ArrayList<>(notices);
    }

    @SuppressWarnings("unchecked")
    private static void addNotices(Set<String> target, Map<String, Object> result)
    {
        if (result == null || !(result.get("notices") instanceof List)) return;
        for (Object notice : (List<Object>) result.get("notices"))
        {
            if (notice != null) target.add(String.valueOf(notice));
        }
    }

    private static List<Long> distinctOrgs(List<Map<String, Object>> rows)
    {
        Set<Long> orgs = new LinkedHashSet<>();
        for (Map<String, Object> row : rows) orgs.add(longValue(row.get("orgId")));
        return new ArrayList<>(orgs);
    }

    private static Map<String, Object> findOrg(List<Map<String, Object>> rows, Long orgId)
    {
        for (Map<String, Object> row : rows)
        {
            if (orgId.equals(longValue(row.get("orgId")))) return row;
        }
        return null;
    }

    private static Map<String, Object> findEnergy(List<Map<String, Object>> energies, String key)
    {
        for (Map<String, Object> energy : energies)
        {
            if (key.equals(energyKey(energy))) return energy;
        }
        return null;
    }

    private static String energyKey(Map<String, Object> energy)
    {
        return text((String) energy.get("subcategory")) + "|" + text((String) energy.get("unitCode"));
    }

    private static String nameOf(Map<String, Object> now, Map<String, Object> then)
    {
        if (now != null && now.get("orgName") != null) return String.valueOf(now.get("orgName"));
        if (then != null && then.get("orgName") != null) return String.valueOf(then.get("orgName"));
        return "";
    }

    private static BigDecimal delta(BigDecimal current, BigDecimal previous)
    {
        if (current == null || previous == null) return null;
        return current.subtract(previous);
    }

    private static BigDecimal rate(BigDecimal current, BigDecimal previous)
    {
        if (current == null || previous == null || previous.signum() == 0) return null;
        return current.subtract(previous).divide(previous, 6, RoundingMode.HALF_UP);
    }

    private static BigDecimal decimal(Object value)
    {
        if (value == null) return null;
        if (value instanceof BigDecimal) return (BigDecimal) value;
        return new BigDecimal(String.valueOf(value));
    }

    private static long longValue(Object value)
    {
        if (value instanceof Number) return ((Number) value).longValue();
        return Long.parseLong(String.valueOf(value));
    }

    private static final class Winner
    {
        private final long templateId;
        private final String endTime;

        private Winner(long templateId, String endTime)
        {
            this.templateId = templateId;
            this.endTime = endTime;
        }
    }

    private static final class Picked
    {
        private final AnalysisFact fact;
        private final String period;

        private Picked(AnalysisFact fact, String period)
        {
            this.fact = fact;
            this.period = period;
        }
    }

    private static final class Bucket
    {
        private final Long orgId;
        private final String orgName;
        private final String period;
        private BigDecimal carbon = ZERO;
        private final Map<String, Energy> energies = new LinkedHashMap<>();

        private Bucket(Long orgId, String orgName, String period)
        {
            this.orgId = orgId;
            this.orgName = orgName;
            this.period = period;
        }
    }

    private static final class Energy
    {
        private String subcategory;
        private String subcategoryName;
        private String categoryL1;
        private String categoryL2;
        private String categoryL3;
        private String unitCode;
        private String unitName;
        private BigDecimal energy = ZERO;
        private BigDecimal carbon = ZERO;
    }
}
