package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.service.EmissionCalculationService;
import com.example.carbon.emission.model.service.EmissionDataFreshnessService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.*;
import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class MonthlyRepairService {
    public static final String ZONE = "Asia/Shanghai";
    private static final Logger log = LoggerFactory.getLogger(MonthlyRepairService.class);
    private final TemplateRepository templates;
    private final EmissionNodeRepository nodes;
    private final EmissionNodeConfigRepository configs;
    private final NodeInclusionResolver inclusion;
    private final MonthlyCalcNodeSummaryRepository summaries;
    private final MonthlyCompanyEnergySummaryRepository companyRows;
    private final CalculationTemplateRepository tasks;
    private final EmissionCalculationService calculation;
    private final EmissionDataFreshnessService freshness;
    private final MonthlyPublicationCoordinator publication;
    private final StatisticsBaselineTemplateService baselines;
    private final CompanyOwnershipService companies;
    private final JdbcTemplate jdbc;
    private final EnergyMeasurementCalculator measurement;
    private final FactorDimensionService factors;

    public MonthlyRepairService(TemplateRepository templates, EmissionNodeRepository nodes,
            EmissionNodeConfigRepository configs, NodeInclusionResolver inclusion,
            MonthlyCalcNodeSummaryRepository summaries, MonthlyCompanyEnergySummaryRepository companyRows,
            CalculationTemplateRepository tasks, EmissionCalculationService calculation,
            EmissionDataFreshnessService freshness, MonthlyPublicationCoordinator publication,
            StatisticsBaselineTemplateService baselines, CompanyOwnershipService companies, JdbcTemplate jdbc,
            EnergyMeasurementCalculator measurement, FactorDimensionService factors) {
        this.templates = templates;
        this.nodes = nodes;
        this.configs = configs;
        this.inclusion = inclusion;
        this.summaries = summaries;
        this.companyRows = companyRows;
        this.tasks = tasks;
        this.calculation = calculation;
        this.freshness = freshness;
        this.publication = publication;
        this.baselines = baselines;
        this.companies = companies;
        this.jdbc = jdbc;
        this.measurement = measurement;
        this.factors = factors;
    }

    public void run(LocalDateTime now) {
        YearMonth month = YearMonth.from(now).minusMonths(1);
        var points = new HashMap<MonthlyRepairContext.Point, PointState>();
        for (Template template : templates.findByEnabledTrueAndTemplateType(2)) {
            try {
                if (companies.registeredId(template.getDeptId()) == null) {
                    log.info("跳过月度补齐，模板未归属已登记公司，模板={}，部门={}，月份={}",
                            template.getId(), template.getDeptId(), month);
                    continue;
                }
                repair(template, now, month, points);
            } catch (RuntimeException failure) {
                log.error("月度补齐失败，模板={}，月份={}", template.getId(), month, failure);
            }
        }
    }

    private void repair(Template template, LocalDateTime now, YearMonth month,
                        Map<MonthlyRepairContext.Point, PointState> points) {
        var tree = nodes.findByTemplateId(template.getId());
        var included = inclusion.resolve(tree);
        var byId = tree.stream().collect(Collectors.toMap(EmissionNode::getId, Function.identity()));
        var expected = new HashSet<NodeEnergy>();
        var waiting = new HashSet<MonthlyRepairContext.Point>();
        boolean pointNeedsRepair = false;
        for (var config : configs.findCollectionPointConfigsByTemplateId(template.getId())) {
            EmissionNode node = byId.get(config.getNodeId());
            if (node == null || !Integer.valueOf(3).equals(node.getTypeId()) || !included.get(node.getId()).included()
                    || config.getCollectionPointType() == null || config.getCollectionPointId() == null) continue;
            var point = new MonthlyRepairContext.Point(config.getCollectionPointType(), config.getCollectionPointId());
            PointState state = points.computeIfAbsent(point, key -> checkPoint(key, month, now));
            String subcategory = config.getEmissionSubcategory();
            if (subcategory == null || subcategory.isBlank()) subcategory = state.subcategory();
            if (subcategory != null && !subcategory.isBlank()) {
                String code = factors.resolveSubcategoryCode(subcategory);
                var visited = new HashSet<Long>();
                for (EmissionNode parent = byId.get(node.getParentId()); parent != null;
                     parent = byId.get(parent.getParentId())) {
                    if (!visited.add(parent.getId())) throw new IllegalStateException("核算节点层级存在循环");
                    if (!Integer.valueOf(1).equals(parent.getTypeId()) && !Integer.valueOf(2).equals(parent.getTypeId())) {
                        break;
                    }
                    expected.add(new NodeEnergy(parent.getId(), code));
                }
            }
            if (state.waiting()) waiting.add(point);
            pointNeedsRepair |= !state.waiting() && state.needsRepair();
        }
        if (expected.isEmpty()) return;
        var existing = summaries.findByTemplateIdAndYearAndMonth(template.getId(), month.getYear(), month.getMonthValue());
        var stored = existing.stream().map(row -> new NodeEnergy(row.getSourceNodeId(), row.getEmissionSubcategory()))
                .collect(Collectors.toSet());
        boolean complete = stored.containsAll(expected) && existing.stream().allMatch(MonthlyRepairService::complete);
        boolean deadline = now.getDayOfMonth() >= 26;
        boolean companyNeeded = template.getDeptId() != null
                && baselines.isBaseline(template.getDeptId(), template.getId())
                && !companyRows.existsByCompanyDeptIdAndYearAndMonth(template.getDeptId(), month.getYear(), month.getMonthValue())
                && (deadline || waiting.isEmpty());
        if (complete && !pointNeedsRepair && !companyNeeded) return;
        long revision = freshness.currentRevision(template.getId());
        var prior = tasks.findFirstByTemplateIdAndCalculationCycleStartDateAndCalculationCycleEndDateAndDataRevisionOrderByIdDesc(
                template.getId(), month.atDay(1), month.atEndOfMonth(), revision);
        // Use the formal entry point for new calculations and its normal deduplication.
        CalculationTemplate task = prior.filter(t -> Integer.valueOf(CalculationTemplate.STATUS_SUCCESS).equals(t.getStatus()))
                .orElseGet(() -> calculation.executeEmissionCalculation(template.getId(), month.atDay(1),
                        month.atEndOfMonth(), 0L, "月度补齐", false));
        if (task != null && Integer.valueOf(CalculationTemplate.STATUS_SUCCESS).equals(task.getStatus())) {
            publication.repair(task, template, new MonthlyRepairContext(month, deadline, waiting, revision));
        }
    }

    private static boolean complete(MonthlyCalcNodeSummary row) {
        return Integer.valueOf(1).equals(row.getResultStatus());
    }

    private PointState checkPoint(MonthlyRepairContext.Point point, YearMonth month, LocalDateTime now) {
        String table = switch (point.type()) {
            case 1 -> "emission_meter_info";
            case 2 -> "emission_fossil_fuel_meter_info";
            case 3 -> "emission_purchased_heat_meter_info";
            default -> throw new IllegalArgumentException("不支持的月度采集点类型");
        };
        return jdbc.query("select meter_reading_method,is_cumulative,billing_cycle_unit,billing_cycle_start_date,"
                        + "billing_cycle_length,last_collection_time,emission_subcategory"
                        + (point.type() == 1 ? ",is_virtual_meter,is_allocation_child" : "")
                        + " from " + table + " where id=?", rs -> {
            if (!rs.next()) return new PointState(true, false, null);
            String subcategory = rs.getString("emission_subcategory");
            boolean derived = point.type() == 1 && (rs.getInt("is_virtual_meter") == 1 || rs.getInt("is_allocation_child") == 1);
            boolean automatic = rs.getInt("meter_reading_method") == 1 && !derived;
            LocalDateTime last = rs.getObject("last_collection_time", LocalDateTime.class);
            if (automatic && (last == null || last.isBefore(month.plusMonths(1).atDay(1).atStartOfDay()))
                    && !DataCollectionServiceImpl.needToCollect(now, last, rs.getObject("billing_cycle_unit", Integer.class),
                    rs.getObject("billing_cycle_start_date", Integer.class), rs.getObject("billing_cycle_length", Integer.class))) {
                return new PointState(true, false, subcategory);
            }
            var observed = measurement.calculate(point.type(), point.id(), rs.getInt("is_cumulative"),
                    month.atDay(1), month.atEndOfMonth());
            boolean waiting = !automatic && !derived && Integer.valueOf(2).equals(observed.getDataStatus());
            boolean complete = Integer.valueOf(1).equals(observed.getDataStatus());
            boolean needsRepair = !Boolean.TRUE.equals(jdbc.query("select data_status from emission_collection_node_data_month "
                            + "where collection_point_type=? and collection_point_id=? and year=? and month=?",
                    result -> result.next() && (complete ? result.getInt(1) == 1 : result.getInt(1) != 2),
                    point.type(), point.id(), month.getYear(), month.getMonthValue()));
            return new PointState(waiting, needsRepair, subcategory);
        }, point.id());
    }

    private record NodeEnergy(Long id, String code) {}
    private record PointState(boolean waiting, boolean needsRepair, String subcategory) {}
}
