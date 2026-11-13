package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.CalcUnitDefaultRepository;
import com.example.carbon.emission.model.repository.CalculationNodeRepository;
import com.example.carbon.emission.model.repository.DataDictItemRepository;
import com.example.carbon.emission.model.service.UnitConversionService;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.YearMonth;
import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

/** 在事务外由采集点月度候选数据构建节点和分公司月度候选数据。 */
@Service
public class MonthlyStatisticsBuilder {

    private static final int ENERGY_SCALE = 6;
    private static final int CARBON_SCALE = 9;
    private static final int TYPE_ROOT = 1;
    private static final int TYPE_CALCULATION = 2;
    private static final int TYPE_COLLECTION = 3;
    private static final int SOURCE_DIRECT = 1;
    private static final int SOURCE_CHILDREN = 2;

    private final CalculationNodeRepository calculationNodes;
    private final UnitConversionService unitConversions;
    private final FactorDimensionService factorDimensions;
    private final CalcUnitDefaultRepository unitDefaults;
    private final DataDictItemRepository dictItems;
    private final StatisticsBaselineTemplateService baselines;

    public MonthlyStatisticsBuilder(CalculationNodeRepository calculationNodes,
                                    UnitConversionService unitConversions,
                                    FactorDimensionService factorDimensions,
                                    CalcUnitDefaultRepository unitDefaults,
                                    DataDictItemRepository dictItems,
                                    StatisticsBaselineTemplateService baselines) {
        this.calculationNodes = calculationNodes;
        this.unitConversions = unitConversions;
        this.factorDimensions = factorDimensions;
        this.unitDefaults = unitDefaults;
        this.dictItems = dictItems;
        this.baselines = baselines;
    }

    public MonthlyPublicationPlan build(CalculationTemplate task, Template template,
                                        MonthlyCollectionDataService.PublicationBatch batch) {
        Long companyDeptId = task.getCompanyDeptId() == null ? template.getDeptId() : task.getCompanyDeptId();
        boolean baseline = baselines.isBaseline(companyDeptId, template.getId());
        if (batch.months().isEmpty()) {
            return new MonthlyPublicationPlan(template.getId(), companyDeptId, baseline,
                    List.of(), List.of(), List.of(), List.of());
        }

        List<CalculationNode> allNodes = calculationNodes.findByCalculationTemplateId(task.getId()).stream()
                .filter(node -> !Boolean.FALSE.equals(node.getIncludeInCalculation()))
                .toList();
        Map<Long, CalculationNode> byId = allNodes.stream()
                .collect(Collectors.toMap(CalculationNode::getId, Function.identity()));
        Map<Long, List<CalculationNode>> children = allNodes.stream()
                .filter(node -> node.getParentId() != null)
                .collect(Collectors.groupingBy(CalculationNode::getParentId));
        List<CalculationNode> targets = allNodes.stream().filter(this::isTarget).toList();

        Map<Long, Integer> levels = new HashMap<>();
        for (CalculationNode target : targets) {
            computeLevel(target.getId(), byId, levels, new HashSet<>());
        }
        List<CalculationNode> bottomUp = new ArrayList<>(targets);
        bottomUp.sort(Comparator.comparingInt((CalculationNode node) -> levels.get(node.getId())).reversed());

        Map<YearMonth, Map<Long, MonthlyCollectionDataService.CollectionCandidate>> candidateByMonthAndNode =
                batch.candidates().stream().collect(Collectors.groupingBy(
                        candidate -> yearMonth(candidate.monthlyData()),
                        Collectors.toMap(candidate -> candidate.sourceNode().getId(), Function.identity())));

        Map<String, String> categoryCache = new HashMap<>();
        List<MonthlyCalcNodeSummary> nodeRows = new ArrayList<>();
        for (YearMonth month : batch.months()) {
            Map<Long, MonthlyCollectionDataService.CollectionCandidate> monthCandidates =
                    candidateByMonthAndNode.getOrDefault(month, Map.of());
            Map<Long, Map<String, Aggregate>> aggregatesByTarget = new HashMap<>();
            Map<Long, Boolean> abnormalByTarget = new HashMap<>();

            for (CalculationNode target : bottomUp) {
                List<CalculationNode> directChildren = children.getOrDefault(target.getId(), List.of());
                Map<String, Aggregate> direct = directAggregates(directChildren, monthCandidates);
                Map<String, Aggregate> childTotals = childAggregates(directChildren, aggregatesByTarget);
                Set<String> keys = new TreeSet<>();
                keys.addAll(direct.keySet());
                keys.addAll(childTotals.keySet());

                boolean directAbnormal = directChildren.stream()
                        .filter(child -> Integer.valueOf(TYPE_COLLECTION).equals(child.getTypeId()))
                        .map(CalculationNode::getId)
                        .map(monthCandidates::get)
                        .filter(Objects::nonNull)
                        .anyMatch(candidate -> !Integer.valueOf(1).equals(candidate.monthlyData().getDataStatus()));
                boolean descendantAbnormal = directChildren.stream()
                        .filter(this::isTarget)
                        .anyMatch(child -> abnormalByTarget.getOrDefault(child.getId(), false));
                boolean abnormal = directAbnormal || descendantAbnormal;
                abnormalByTarget.put(target.getId(), abnormal);

                String missingIds = directMissingIds(directChildren, monthCandidates);
                Map<String, Aggregate> completed = new HashMap<>();
                for (String subcategory : keys) {
                    Aggregate own = direct.getOrDefault(subcategory, Aggregate.empty());
                    Aggregate child = childTotals.getOrDefault(subcategory, Aggregate.empty());
                    Aggregate total = new Aggregate(own.directEnergy(), own.directCarbon(),
                            own.directEnergy().add(child.subtotalEnergy()),
                            own.directCarbon().add(child.subtotalCarbon()));
                    completed.put(subcategory, total);
                    nodeRows.add(nodeRow(task, template, target, byId, directChildren, levels,
                            month, subcategory, own, total,
                            (direct.containsKey(subcategory) ? SOURCE_DIRECT : 0)
                                    | (childTotals.containsKey(subcategory) ? SOURCE_CHILDREN : 0),
                            abnormal, missingIds, categoryCache));
                }
                aggregatesByTarget.put(target.getId(), completed);
            }
        }

        List<MonthlyCompanyEnergySummary> companyRows = baseline
                ? buildCompanyRows(task, companyDeptId, batch, categoryCache) : List.of();
        return new MonthlyPublicationPlan(template.getId(), companyDeptId, baseline, batch.months(),
                batch.rows(), nodeRows, companyRows);
    }

    private Map<String, Aggregate> directAggregates(List<CalculationNode> directChildren,
            Map<Long, MonthlyCollectionDataService.CollectionCandidate> monthCandidates) {
        Map<String, Aggregate> result = new HashMap<>();
        for (CalculationNode child : directChildren) {
            if (!Integer.valueOf(TYPE_COLLECTION).equals(child.getTypeId())) continue;
            MonthlyCollectionDataService.CollectionCandidate candidate = monthCandidates.get(child.getId());
            if (candidate == null) continue;
            MonthlyCollectionNodeData row = candidate.monthlyData();
            String subcategory = factorDimensions.resolveSubcategoryCode(row.getEmissionSubcategory());
            BigDecimal energy = unitConversions.convertToCalculationUnitRequired(subcategory,
                    row.getMeasurementUnit(), nvl(row.getAdjustedEnergyValue()));
            BigDecimal carbon = nvl(row.getAdjustedCarbonEmission());
            Aggregate previous = result.getOrDefault(subcategory, Aggregate.empty());
            result.put(subcategory, new Aggregate(previous.directEnergy().add(energy),
                    previous.directCarbon().add(carbon), BigDecimal.ZERO, BigDecimal.ZERO));
        }
        return result;
    }

    private Map<String, Aggregate> childAggregates(List<CalculationNode> directChildren,
                                                    Map<Long, Map<String, Aggregate>> completed) {
        Map<String, Aggregate> result = new HashMap<>();
        for (CalculationNode child : directChildren) {
            if (!isTarget(child)) continue;
            for (Map.Entry<String, Aggregate> entry : completed.getOrDefault(child.getId(), Map.of()).entrySet()) {
                Aggregate previous = result.getOrDefault(entry.getKey(), Aggregate.empty());
                Aggregate value = entry.getValue();
                result.put(entry.getKey(), new Aggregate(BigDecimal.ZERO, BigDecimal.ZERO,
                        previous.subtotalEnergy().add(value.subtotalEnergy()),
                        previous.subtotalCarbon().add(value.subtotalCarbon())));
            }
        }
        return result;
    }

    private MonthlyCalcNodeSummary nodeRow(CalculationTemplate task, Template template,
            CalculationNode target, Map<Long, CalculationNode> byId, List<CalculationNode> directChildren,
            Map<Long, Integer> levels, YearMonth month, String subcategory, Aggregate own,
            Aggregate total, int summarySource, boolean abnormal, String missingIds,
            Map<String, String> categoryCache) {
        MonthlyCalcNodeSummary row = new MonthlyCalcNodeSummary();
        row.setTemplateId(template.getId());
        row.setSourceNodeId(target.getNodeId());
        CalculationNode parent = target.getParentId() == null ? null : byId.get(target.getParentId());
        row.setParentSourceNodeId(parent == null ? null : parent.getNodeId());
        row.setYear(month.getYear());
        row.setMonth(month.getMonthValue());
        row.setNodeLevel(levels.getOrDefault(target.getId(), 1));
        row.setIsLeafCalcNode(!directChildren.isEmpty() && directChildren.stream()
                .allMatch(childNode -> Integer.valueOf(TYPE_COLLECTION).equals(childNode.getTypeId())) ? 1 : 0);
        row.setEmissionSubcategory(subcategory);
        row.setEmissionCategory(category(categoryCache, subcategory));
        row.setDirectEnergyValue(scaleEnergy(own.directEnergy()));
        row.setDirectCarbonEmission(scaleCarbon(own.directCarbon()));
        row.setSubtotalEnergyValue(scaleEnergy(total.subtotalEnergy()));
        row.setSubtotalCarbonEmission(scaleCarbon(total.subtotalCarbon()));
        row.setCalculationUnitCode(unitDefaults.findBySubcategoryCode(subcategory)
                .map(CalcUnitDefault::getCalculationUnit)
                .orElseThrow(() -> new IllegalStateException("未配置缺省核算单位：" + subcategory)));
        row.setCarbonEmissionFactor(effectiveFactor(total.subtotalCarbon(), total.subtotalEnergy()));
        row.setSummarySource(summarySource);
        row.setResultStatus(abnormal ? 2 : 1);
        row.setMissingCollectionPointIds(missingIds);
        row.setCreatedBy(userId(task));
        row.setUpdatedBy(userId(task));
        return row;
    }

    private List<MonthlyCompanyEnergySummary> buildCompanyRows(CalculationTemplate task, Long companyDeptId,
            MonthlyCollectionDataService.PublicationBatch batch, Map<String, String> categoryCache) {
        if (companyDeptId == null) {
            throw new IllegalStateException("统计基准模板缺少明确的分公司ID");
        }
        List<MonthlyCompanyEnergySummary> rows = new ArrayList<>();
        Map<YearMonth, List<MonthlyCollectionDataService.CollectionCandidate>> byMonth = batch.candidates().stream()
                .collect(Collectors.groupingBy(candidate -> yearMonth(candidate.monthlyData())));
        for (YearMonth month : batch.months()) {
            List<MonthlyCollectionDataService.CollectionCandidate> candidates = byMonth.getOrDefault(month, List.of());
            boolean abnormal = candidates.stream()
                    .anyMatch(candidate -> !Integer.valueOf(1).equals(candidate.monthlyData().getDataStatus()));
            Map<CompanyKey, CompanyAggregate> groups = new TreeMap<>(Comparator
                    .comparing(CompanyKey::energyCategoryL1).thenComparing(CompanyKey::subcategory));
            for (MonthlyCollectionDataService.CollectionCandidate candidate : candidates) {
                MonthlyCollectionNodeData source = candidate.monthlyData();
                if (source.getEnergyCategoryL1() == null || source.getEnergyCategoryL1().isBlank()) {
                    throw new IllegalStateException("采集点缺少能耗一级分类，id=" + source.getCollectionPointId());
                }
                String subcategory = factorDimensions.resolveSubcategoryCode(source.getEmissionSubcategory());
                CalcUnitDefault defaults = unitDefaults.findBySubcategoryCode(subcategory)
                        .orElseThrow(() -> new IllegalStateException("未配置缺省单位：" + subcategory));
                String reportUnit = defaults.getReportUnit();
                BigDecimal energy = unitConversions.convertRequired(subcategory, source.getMeasurementUnit(),
                        reportUnit, nvl(source.getAdjustedEnergyValue()));
                CompanyKey key = new CompanyKey(source.getEnergyCategoryL1().trim(), subcategory);
                CompanyAggregate previous = groups.getOrDefault(key, CompanyAggregate.empty(reportUnit));
                if (!previous.unit().equals(reportUnit)) {
                    throw new IllegalStateException("同一分公司月度分组出现不同标准单位：" + key);
                }
                groups.put(key, new CompanyAggregate(previous.energy().add(energy),
                        previous.carbon().add(nvl(source.getAdjustedCarbonEmission())), reportUnit));
            }
            for (Map.Entry<CompanyKey, CompanyAggregate> entry : groups.entrySet()) {
                CompanyKey key = entry.getKey();
                CompanyAggregate value = entry.getValue();
                MonthlyCompanyEnergySummary row = new MonthlyCompanyEnergySummary();
                row.setCompanyDeptId(companyDeptId);
                row.setYear(month.getYear());
                row.setMonth(month.getMonthValue());
                row.setEnergyCategoryL1(key.energyCategoryL1());
                row.setEmissionCategory(category(categoryCache, key.subcategory()));
                row.setEmissionSubcategory(key.subcategory());
                row.setStandardEnergyValue(scaleEnergy(value.energy()));
                row.setCarbonEmission(scaleCarbon(value.carbon()));
                row.setCarbonEmissionFactor(effectiveFactor(value.carbon(), value.energy()));
                row.setCalculationUnitCode(value.unit());
                row.setResultStatus(abnormal ? 2 : 1);
                row.setIngestStatus(0);
                row.setCreatedBy(userId(task));
                row.setUpdatedBy(userId(task));
                rows.add(row);
            }
        }
        return rows;
    }

    private String directMissingIds(List<CalculationNode> children,
            Map<Long, MonthlyCollectionDataService.CollectionCandidate> monthCandidates) {
        String value = children.stream()
                .filter(child -> Integer.valueOf(TYPE_COLLECTION).equals(child.getTypeId()))
                .filter(child -> {
                    MonthlyCollectionDataService.CollectionCandidate candidate = monthCandidates.get(child.getId());
                    return candidate != null && !Integer.valueOf(1).equals(candidate.monthlyData().getDataStatus());
                })
                .map(CalculationNode::getNodeId)
                .filter(Objects::nonNull)
                .distinct().sorted().map(String::valueOf).collect(Collectors.joining(","));
        if (value.length() > 500) {
            throw new IllegalStateException("直属异常采集节点ID超过500字符，无法完整保存");
        }
        return value.isEmpty() ? null : value;
    }

    private int computeLevel(Long id, Map<Long, CalculationNode> byId,
                             Map<Long, Integer> levels, Set<Long> visiting) {
        if (levels.containsKey(id)) return levels.get(id);
        if (!visiting.add(id)) throw new IllegalStateException("核算快照存在循环父子关系，nodeId=" + id);
        CalculationNode node = byId.get(id);
        int level = node == null || node.getParentId() == null || !byId.containsKey(node.getParentId())
                ? 1 : computeLevel(node.getParentId(), byId, levels, visiting) + 1;
        visiting.remove(id);
        levels.put(id, level);
        return level;
    }

    private boolean isTarget(CalculationNode node) {
        return node.getTypeId() != null && (node.getTypeId() == TYPE_ROOT || node.getTypeId() == TYPE_CALCULATION);
    }

    private String category(Map<String, String> cache, String subcategory) {
        return cache.computeIfAbsent(subcategory, key -> dictItems.findByItemCode(key)
                .map(DataDictItem::getParentCode)
                .orElseThrow(() -> new IllegalStateException("无法解析排放大类，小类=" + key)));
    }

    private BigDecimal effectiveFactor(BigDecimal carbon, BigDecimal energy) {
        return energy.signum() == 0 ? BigDecimal.ZERO
                : carbon.divide(energy, CARBON_SCALE, RoundingMode.HALF_UP);
    }

    private YearMonth yearMonth(MonthlyCollectionNodeData row) {
        return YearMonth.of(row.getYear(), row.getMonth());
    }

    private Long userId(CalculationTemplate task) {
        return task.getInitiatorId() == null ? 0L : task.getInitiatorId();
    }

    private BigDecimal scaleEnergy(BigDecimal value) {
        return value.setScale(ENERGY_SCALE, RoundingMode.HALF_UP);
    }

    private BigDecimal scaleCarbon(BigDecimal value) {
        return value.setScale(CARBON_SCALE, RoundingMode.HALF_UP);
    }

    private BigDecimal nvl(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private record Aggregate(BigDecimal directEnergy, BigDecimal directCarbon,
                             BigDecimal subtotalEnergy, BigDecimal subtotalCarbon) {
        static Aggregate empty() {
            return new Aggregate(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO);
        }
    }

    private record CompanyKey(String energyCategoryL1, String subcategory) { }

    private record CompanyAggregate(BigDecimal energy, BigDecimal carbon, String unit) {
        static CompanyAggregate empty(String unit) {
            return new CompanyAggregate(BigDecimal.ZERO, BigDecimal.ZERO, unit);
        }
    }
}
