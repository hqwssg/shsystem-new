package com.ruoyi.carbon.analysis.service;

import java.time.LocalDate;
import java.time.DateTimeException;
import java.time.YearMonth;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import com.ruoyi.carbon.analysis.domain.AnalysisCategoryOption;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;
import com.ruoyi.carbon.analysis.domain.AnalysisNode;
import com.ruoyi.carbon.analysis.mapper.AnalysisMapper;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class AnalysisService
{
    private static final Set<String> GRAINS = Set.of("month", "quarter", "year");
    private static final Set<String> LEVELS = Set.of("BRANCH", "REGION", "STATION");

    private final AnalysisMapper mapper;
    private final AnalysisAggregator aggregator = new AnalysisAggregator();

    public AnalysisService(AnalysisMapper mapper)
    {
        this.mapper = mapper;
    }

    public Map<String, String> categoryNames()
    {
        Map<String, String> names = new LinkedHashMap<>();
        for (AnalysisCategoryOption option : mapper.selectCategories())
        {
            if (option.getCategoryCode() == null || option.getCategoryName() == null) continue;
            String code = option.getCategoryCode().trim();
            String name = option.getCategoryName().trim();
            if (!code.isEmpty() && !name.isEmpty()) names.put(code, name);
        }
        return names;
    }

    public Map<String, Object> options()
    {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("orgs", mapper.selectOrgs());
        result.put("categories", mapper.selectCategories());
        result.put("subcategories", mapper.selectSubcategories());
        return result;
    }

    public Map<String, Object> query(String grain, String start, String end, String orgLevel, Long parentNodeId,
            String categoryMode, String energyCategory, String subcategory)
    {
        String useGrain = grainOf(grain);
        String level = levelOf(orgLevel);
        LocalDate startDate = parseDate(start, "开始日期", false);
        LocalDate endDate = parseDate(end, "结束日期", true);
        if (endDate.isBefore(startDate))
        {
            throw new ServiceException("结束日期不能早于开始日期");
        }
        return aggregate(useGrain, startDate, endDate, level, parentNodeId, modeOf(categoryMode), energyCategory, subcategory);
    }

    public Map<String, Object> compare(String compareType, String grain, String period, String orgLevel, Long parentNodeId,
            String orgIds, Long orgId, String categoryMode, String energyCategory, String subcategory)
    {
        String useGrain = grainOf(grain);
        String level = levelOf(orgLevel);
        String mode = modeOf(categoryMode);
        LocalDate[] range = periodRange(useGrain, period);
        Map<String, Object> current = aggregate(useGrain, range[0], range[1], level, parentNodeId, mode, energyCategory, subcategory);
        boolean yearOnYear = "yoy".equals(compareType);
        Map<String, Object> compared;
        if (yearOnYear)
        {
            if (orgId == null)
            {
                throw new ServiceException("请选择要比对的组织");
            }
            LocalDate[] previousRange = new LocalDate[] { range[0].minusYears(1), range[1].minusYears(1) };
            Map<String, Object> previous = aggregate(useGrain, previousRange[0], previousRange[1], level, parentNodeId, mode,
                    energyCategory, subcategory);
            compared = aggregator.compare(current, previous, true);
            compared.put("period", period);
            compared.put("previousPeriod", previousLabel(useGrain, period));
            return filterOrgs(compared, Set.of(orgId));
        }
        if (!"org".equals(compareType))
        {
            throw new ServiceException("对比方式不正确");
        }
        compared = aggregator.compare(current, Map.of("rows", List.of(), "notices", List.of()), false);
        compared.put("period", period);
        Set<Long> selected = parseOrgIds(orgIds);
        return selected.isEmpty() ? compared : filterOrgs(compared, selected);
    }

    public LoadedFacts loadFacts(LocalDate start, LocalDate end)
    {
        String rangeStart = start.toString();
        String rangeEnd = end.toString();
        List<AnalysisNode> nodes = mapper.selectNodes(rangeStart, rangeEnd);
        List<AnalysisFact> facts = mergeSummaryAndDirectFacts(
                mapper.selectFacts(rangeStart, rangeEnd),
                mapper.selectDirectFacts(rangeStart, rangeEnd));
        return new LoadedFacts(nodes, facts);
    }

    /**
     * Prefer node summaries, but recover historical tasks whose summary rows were
     * created as zero before their non-zero collection details were finalized.
     */
    static List<AnalysisFact> mergeSummaryAndDirectFacts(List<AnalysisFact> summaries, List<AnalysisFact> directFacts)
    {
        Map<Long, BigDecimal> summaryTotals = carbonTotals(summaries);
        Map<Long, BigDecimal> directTotals = carbonTotals(directFacts);
        Set<Long> useDirect = directTotals.entrySet().stream()
                .filter(entry -> entry.getValue().signum() != 0
                        && summaryTotals.getOrDefault(entry.getKey(), BigDecimal.ZERO).signum() == 0)
                .map(Map.Entry::getKey)
                .collect(Collectors.toSet());
        List<AnalysisFact> facts = new ArrayList<>();
        for (AnalysisFact summary : summaries)
        {
            if (!useDirect.contains(summary.getTemplateId())) facts.add(summary);
        }
        Set<Long> summarized = summaries.stream().map(AnalysisFact::getTemplateId).collect(Collectors.toSet());
        for (AnalysisFact direct : directFacts)
        {
            if (!summarized.contains(direct.getTemplateId()) || useDirect.contains(direct.getTemplateId()))
            {
                facts.add(direct);
            }
        }
        return facts;
    }

    private static Map<Long, BigDecimal> carbonTotals(List<AnalysisFact> facts)
    {
        Map<Long, BigDecimal> totals = new LinkedHashMap<>();
        for (AnalysisFact fact : facts)
        {
            if (fact == null || fact.getTemplateId() == null) continue;
            totals.merge(fact.getTemplateId(),
                    fact.getCarbonValue() == null ? BigDecimal.ZERO : fact.getCarbonValue(),
                    BigDecimal::add);
        }
        return totals;
    }

    public Map<String, Object> queryFacts(LoadedFacts loaded, String grain, LocalDate start, LocalDate end,
            String orgLevel, String categoryMode)
    {
        return aggregator.query(loaded.nodes, loaded.facts, grain, start, end, orgLevel, null, categoryMode, null, null);
    }

    public static final class LoadedFacts
    {
        private final List<AnalysisNode> nodes;
        private final List<AnalysisFact> facts;

        private LoadedFacts(List<AnalysisNode> nodes, List<AnalysisFact> facts)
        {
            this.nodes = nodes;
            this.facts = facts;
        }
    }

    private Map<String, Object> aggregate(String grain, LocalDate start, LocalDate end, String orgLevel, Long parentNodeId,
            String categoryMode, String energyCategory, String subcategory)
    {
        LoadedFacts loaded = loadFacts(start, end);
        return aggregator.query(loaded.nodes, loaded.facts, grain, start, end, orgLevel, parentNodeId, categoryMode, energyCategory, subcategory);
    }

    private Map<String, Object> filterOrgs(Map<String, Object> compared, Set<Long> orgIds)
    {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) compared.get("rows");
        List<Map<String, Object>> kept = new ArrayList<>();
        for (Map<String, Object> row : rows)
        {
            Object orgId = row.get("orgId");
            long id = orgId instanceof Number ? ((Number) orgId).longValue() : Long.parseLong(String.valueOf(orgId));
            if (orgIds.contains(id)) kept.add(row);
        }
        Map<String, Object> copy = new LinkedHashMap<>(compared);
        copy.put("rows", kept);
        copy.put("chartType", kept.size() > 1 ? "bar" : "line");
        return copy;
    }

    static LocalDate[] periodRange(String grain, String period)
    {
        if (period == null || period.isBlank())
        {
            throw new ServiceException("请选择对比周期");
        }
        if ("month".equals(grain))
        {
            YearMonth month = YearMonth.parse(period);
            return new LocalDate[] { month.atDay(1), month.atEndOfMonth() };
        }
        if ("quarter".equals(grain))
        {
            String[] parts = period.split("-Q");
            if (parts.length != 2)
            {
                throw new ServiceException("季度格式应为 2025-Q1");
            }
            int year = Integer.parseInt(parts[0]);
            int quarter = Integer.parseInt(parts[1]);
            if (quarter < 1 || quarter > 4)
            {
                throw new ServiceException("季度格式应为 2025-Q1");
            }
            int month = (quarter - 1) * 3 + 1;
            LocalDate start = LocalDate.of(year, month, 1);
            return new LocalDate[] { start, start.plusMonths(3).minusDays(1) };
        }
        int year = Integer.parseInt(period);
        return new LocalDate[] { LocalDate.of(year, 1, 1), LocalDate.of(year, 12, 31) };
    }

    private static String previousLabel(String grain, String period)
    {
        if ("month".equals(grain)) return YearMonth.parse(period).minusYears(1).toString();
        if ("quarter".equals(grain))
        {
            String[] parts = period.split("-Q");
            return (Integer.parseInt(parts[0]) - 1) + "-Q" + parts[1];
        }
        return String.valueOf(Integer.parseInt(period) - 1);
    }

    private static Set<Long> parseOrgIds(String orgIds)
    {
        Set<Long> ids = new LinkedHashSet<>();
        if (orgIds == null || orgIds.isBlank()) return ids;
        for (String part : orgIds.split(","))
        {
            if (!part.isBlank()) ids.add(Long.parseLong(part.trim()));
        }
        return ids;
    }

    private static String grainOf(String grain)
    {
        if (!GRAINS.contains(grain)) throw new ServiceException("统计粒度不正确");
        return grain;
    }

    private static String levelOf(String orgLevel)
    {
        if (!LEVELS.contains(orgLevel)) throw new ServiceException("组织层级不正确");
        return orgLevel;
    }

    private static String modeOf(String categoryMode)
    {
        if (categoryMode == null || categoryMode.isBlank() || "total".equals(categoryMode)) return "total";
        if ("category".equals(categoryMode)) return "category";
        throw new ServiceException("统计方式不正确");
    }

    static LocalDate parseDate(String text, String label, boolean endBoundary)
    {
        if (text == null || text.isBlank()) throw new ServiceException("请填写" + label);
        String value = text.trim();
        try
        {
            if (value.matches("\\d{4}"))
            {
                int year = Integer.parseInt(value);
                return endBoundary ? LocalDate.of(year, 12, 31) : LocalDate.of(year, 1, 1);
            }
            if (value.matches("\\d{4}-\\d{2}"))
            {
                YearMonth month = YearMonth.parse(value);
                return endBoundary ? month.atEndOfMonth() : month.atDay(1);
            }
            if (value.length() >= 10)
            {
                return LocalDate.parse(value.substring(0, 10));
            }
        }
        catch (DateTimeException | NumberFormatException ex)
        {
            throw new ServiceException(label + "格式不正确，请使用 yyyy、yyyy-MM 或 yyyy-MM-dd");
        }
        throw new ServiceException(label + "格式不正确，请使用 yyyy、yyyy-MM 或 yyyy-MM-dd");
    }
}
