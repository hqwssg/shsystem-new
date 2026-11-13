package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.*;

/** 从一次成功核算中生成物理采集点的最新月度结果。 */
@Service
public class MonthlyCollectionDataService {

    private static final int SCALE = 9;
    private static final Set<String> AUTOMATIC_CYCLES = Set.of("MONTHLY", "QUARTERLY", "YEARLY");

    private final CalculationNodeRepository calculationNodes;
    private final CalculationNodeDataRepository calculationData;
    private final MeterInfoRepository meters;
    private final FossilFuelMeterInfoRepository fossilMeters;
    private final PurchasedHeatMeterInfoRepository heatMeters;
    private final EnergyMeasurementCalculator measurementCalculator;
    private final FactorDimensionService factorDimensionService;
    private final MonthlyCollectionDataWriter writer;
    private final ObjectMapper objectMapper;

    public MonthlyCollectionDataService(CalculationNodeRepository calculationNodes,
                                        CalculationNodeDataRepository calculationData,
                                        MeterInfoRepository meters,
                                        FossilFuelMeterInfoRepository fossilMeters,
                                        PurchasedHeatMeterInfoRepository heatMeters,
                                        EnergyMeasurementCalculator measurementCalculator,
                                        FactorDimensionService factorDimensionService,
                                        MonthlyCollectionDataWriter writer,
                                        ObjectMapper objectMapper) {
        this.calculationNodes = calculationNodes;
        this.calculationData = calculationData;
        this.meters = meters;
        this.fossilMeters = fossilMeters;
        this.heatMeters = heatMeters;
        this.measurementCalculator = measurementCalculator;
        this.factorDimensionService = factorDimensionService;
        this.writer = writer;
        this.objectMapper = objectMapper;
    }

    public int publish(CalculationTemplate task, Template template, boolean requested) {
        PublicationBatch batch = prepare(task, template, requested);
        List<MonthlyCollectionNodeData> rows = batch.rows();
        if (!rows.isEmpty()) {
            writer.replace(rows);
        }
        return rows.size();
    }

    /**
     * 在事务外构建完整的月度候选数据。统一发布协调器会把这些候选数据与
     * 节点、分公司月度候选数据放入同一个独立事务中提交。
     */
    public PublicationBatch prepare(CalculationTemplate task, Template template, boolean requested) {
        return prepare(task, template, requested, false);
    }

    PublicationBatch prepare(CalculationTemplate task, Template template, boolean requested, boolean nightly) {
        if (!requested || task == null || template == null
                || (!nightly && task.isReusedExistingResult())
                || !Integer.valueOf(CalculationTemplate.STATUS_SUCCESS).equals(task.getStatus())) {
            return PublicationBatch.empty();
        }
        boolean manual = Integer.valueOf(2).equals(task.getTaskInitiator());
        if (!nightly && !manual && !AUTOMATIC_CYCLES.contains(cycleType(template.getTaskConfig()))) {
            return PublicationBatch.empty();
        }

        List<YearMonth> months = completeMonths(task.getCalculationCycleStartDate(),
                task.getCalculationCycleEndDate());
        if (months.isEmpty()) {
            return PublicationBatch.empty();
        }

        List<CalculationNode> nodes = calculationNodes.findByCalculationTemplateId(task.getId()).stream()
                .filter(node -> Integer.valueOf(3).equals(node.getTypeId()))
                .filter(node -> !Boolean.FALSE.equals(node.getIncludeInCalculation()))
                .toList();
        Map<Long, CalculationNode> byId = new HashMap<>();
        nodes.forEach(node -> byId.put(node.getId(), node));
        List<CalculationNodeData> sources = calculationData.findByCalculationNodeIdIn(byId.keySet()).stream()
                .filter(data -> data.getCollectionPointType() != null && data.getCollectionPointId() != null)
                .toList();

        Map<PointKey, CalculationNodeData> uniqueSources = new LinkedHashMap<>();
        for (CalculationNodeData source : sources) {
            PointKey key = new PointKey(source.getCollectionPointType(), source.getCollectionPointId());
            CalculationNodeData previous = uniqueSources.putIfAbsent(key, source);
            if (previous != null) {
                CalculationNode first = byId.get(previous.getCalculationNodeId());
                CalculationNode second = byId.get(source.getCalculationNodeId());
                throw new IllegalStateException("同一核算模板重复引用物理采集点 type=" + key.type()
                        + ", id=" + key.id() + "，冲突节点=" + nodeName(first) + "、" + nodeName(second));
            }
        }

        List<CollectionCandidate> candidates = new ArrayList<>();
        for (CalculationNodeData source : uniqueSources.values()) {
            Attribution attribution = attribution(source.getCollectionPointType(), source.getCollectionPointId());
            CalculationNode sourceNode = byId.get(source.getCalculationNodeId());
            for (YearMonth month : months) {
                candidates.add(new CollectionCandidate(sourceNode, source,
                        calculateRow(source, attribution, month, task.getInitiatorId())));
            }
        }
        return new PublicationBatch(List.copyOf(months), List.copyOf(candidates));
    }

    List<YearMonth> completeMonths(LocalDate start, LocalDate end) {
        if (start == null || end == null || start.isAfter(end)
                || start.getDayOfMonth() != 1 || !end.equals(YearMonth.from(end).atEndOfMonth())) {
            return List.of();
        }
        List<YearMonth> months = new ArrayList<>();
        for (YearMonth month = YearMonth.from(start); !month.isAfter(YearMonth.from(end)); month = month.plusMonths(1)) {
            months.add(month);
        }
        return months;
    }

    private MonthlyCollectionNodeData calculateRow(CalculationNodeData source, Attribution attribution,
                                                    YearMonth month, Long userId) {
        EnergyMeasurementCalculator.Result result = measurementCalculator.calculate(
                source.getCollectionPointType(), source.getCollectionPointId(), source.getIsCumulative(),
                month.atDay(1), month.atEndOfMonth());
        FactorDimensionService.CarbonResult raw = factorDimensionService.calculate(
                source.getEmissionSubcategory(), result.getEnergyMeasurementValue(), source.getMeasurementUnit(),
                source.getCarbonEmissionFactor(), source.getCarbonEmissionFactorUnit());
        FactorDimensionService.CarbonResult adjusted = factorDimensionService.calculate(
                source.getEmissionSubcategory(), result.getAdjustedEnergyValue(), source.getMeasurementUnit(),
                source.getCarbonEmissionFactor(), source.getCarbonEmissionFactorUnit());

        MonthlyCollectionNodeData row = new MonthlyCollectionNodeData();
        row.setYear(month.getYear());
        row.setMonth(month.getMonthValue());
        row.setCollectionPointType(source.getCollectionPointType());
        row.setCollectionPointId(source.getCollectionPointId());
        row.setEmissionCategory(source.getEmissionCategory());
        row.setEmissionSubcategory(source.getEmissionSubcategory());
        row.setCarbonEmissionFactor(source.getCarbonEmissionFactor());
        row.setCarbonEmissionFactorUnit(source.getCarbonEmissionFactorUnit());
        row.setCarbonEmissionUnit(FactorDimensionService.CARBON_RESULT_UNIT);
        row.setIsCumulative(source.getIsCumulative());
        row.setIsMobileSource(source.getIsMobileSource());
        row.setMeasurementUnit(source.getMeasurementUnit());
        row.setEnergyCategoryL1(source.getEnergyCategoryL1());
        row.setEnergyCategoryL2(source.getEnergyCategoryL2());
        row.setEnergyCategoryL3(source.getEnergyCategoryL3());
        row.setEnergyUseCategory(source.getEnergyUseCategory());
        row.setEnergyMeasurementValue(result.getEnergyMeasurementValue());
        row.setCarbonEmission(raw.carbonTco2e().setScale(SCALE, RoundingMode.HALF_UP));
        row.setAdjustedEnergyValue(result.getAdjustedEnergyValue());
        row.setAdjustedCarbonEmission(adjusted.carbonTco2e().setScale(SCALE, RoundingMode.HALF_UP));
        row.setRolloverApplied(result.getRolloverApplied());
        row.setRolloverThreshold(result.getRolloverThreshold());
        row.setTotalEmissionCalcMethod(source.getTotalEmissionCalcMethod());
        row.setCollectionRecordStartDate(result.getCollectionRecordStartDate());
        row.setCollectionRecordEndDate(result.getCollectionRecordEndDate());
        row.setDataStatus(result.getDataStatus());
        row.setDataMissingDescription(result.getDataMissingDescription());
        row.setEnergyAttributionDeptId(attribution.departmentId());
        row.setEnergyAttributionStationId(attribution.stationId());
        row.setCreatedBy(userId == null ? 0L : userId);
        row.setUpdatedBy(userId == null ? 0L : userId);
        return row;
    }

    private Attribution attribution(Integer type, Long id) {
        return switch (type) {
            case 1 -> meters.findById(id)
                    .map(point -> new Attribution(point.getEnergyAttributionDeptId(), point.getEnergyAttributionStationId()))
                    .orElseThrow(() -> missing(type, id));
            case 2 -> fossilMeters.findById(id)
                    .map(point -> new Attribution(point.getEnergyAttributionDeptId(), point.getEnergyAttributionStationId()))
                    .orElseThrow(() -> missing(type, id));
            case 3 -> heatMeters.findById(id)
                    .map(point -> new Attribution(point.getEnergyAttributionDeptId(), point.getEnergyAttributionStationId()))
                    .orElseThrow(() -> missing(type, id));
            default -> throw new IllegalArgumentException("不支持的采集点类型: " + type);
        };
    }

    private IllegalStateException missing(Integer type, Long id) {
        return new IllegalStateException("采集点不存在: type=" + type + ", id=" + id);
    }

    private String cycleType(String taskConfig) {
        if (taskConfig == null || taskConfig.isBlank()) return "MONTHLY";
        try {
            JsonNode root = objectMapper.readTree(taskConfig);
            return root.path("cycleType").asText("MONTHLY").trim().toUpperCase(Locale.ROOT);
        } catch (Exception ignored) {
            return "MONTHLY";
        }
    }

    private String nodeName(CalculationNode node) {
        return node == null || node.getName() == null ? "未知节点" : node.getName();
    }

    private record PointKey(Integer type, Long id) {}
    private record Attribution(Long departmentId, Long stationId) {}

    public record CollectionCandidate(CalculationNode sourceNode,
                                      CalculationNodeData sourceData,
                                      MonthlyCollectionNodeData monthlyData) { }

    public record PublicationBatch(List<YearMonth> months,
                                   List<CollectionCandidate> candidates) {
        public PublicationBatch {
            months = List.copyOf(months);
            candidates = List.copyOf(candidates);
        }

        public List<MonthlyCollectionNodeData> rows() {
            return candidates.stream().map(CollectionCandidate::monthlyData).toList();
        }

        public static PublicationBatch empty() {
            return new PublicationBatch(List.of(), List.of());
        }
    }
}
