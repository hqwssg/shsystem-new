package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary;
import com.example.carbon.emission.model.repository.MonthlyCalcNodeSummaryRepository;
import com.example.carbon.emission.model.repository.MonthlyCollectionNodeDataRepository;
import com.example.carbon.emission.model.repository.MonthlyCompanyEnergySummaryRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.YearMonth;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

/** 锁定业务模板后，在同一独立事务中整体替换三类月度结果。 */
@Service
public class MonthlyPublicationWriter {

    private final MonthlyCollectionNodeDataRepository collectionRows;
    private final MonthlyCalcNodeSummaryRepository nodeRows;
    private final MonthlyCompanyEnergySummaryRepository companyRows;
    private final JdbcTemplate jdbc;
    @Autowired(required = false)
    private MonthlyPredictionOutbox prediction;

    public MonthlyPublicationWriter(MonthlyCollectionNodeDataRepository collectionRows,
                                    MonthlyCalcNodeSummaryRepository nodeRows,
                                    MonthlyCompanyEnergySummaryRepository companyRows,
                                    JdbcTemplate jdbc) {
        this.collectionRows = collectionRows;
        this.nodeRows = nodeRows;
        this.companyRows = companyRows;
        this.jdbc = jdbc;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void replace(MonthlyPublicationPlan plan) {
        write(plan, null);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void repair(MonthlyPublicationPlan plan, MonthlyRepairContext context) {
        write(plan, context);
    }

    private void write(MonthlyPublicationPlan plan, MonthlyRepairContext context) {
        lockTemplate(plan.templateId());
        if (context != null) {
            Long revision = jdbc.query("select data_revision from emission_data_freshness where template_id=? for update",
                    rs -> rs.next() ? rs.getLong(1) : 0L, plan.templateId());
            if (revision == null || revision != context.revision()) {
                throw new IllegalStateException("采集数据版本已变化，请在下次扫描重新核算");
            }
        }
        boolean publishCompany = plan.baselineTemplate() && (prediction == null
                || prediction.lockBaseline(plan.companyDeptId(), plan.templateId()));
        List<PointKey> points = plan.collectionRows().stream()
                .map(row -> new PointKey(row.getCollectionPointType(), row.getCollectionPointId()))
                .distinct().sorted(Comparator.comparing(PointKey::type).thenComparing(PointKey::id)).toList();
        points.forEach(this::lockPhysicalPoint);

        List<MonthlyCollectionNodeData> collections = plan.collectionRows().stream()
                .filter(row -> context == null || repairCollection(row, context)).toList();
        List<MonthlyCompanyEnergySummary> companies = publishCompany ? plan.companyRows().stream()
                .filter(row -> context == null || canRepairCompany(row, context)).toList() : List.of();
        if (context != null && !context.waitingPoints().isEmpty()) {
            companies.forEach(row -> row.setResultStatus(2));
        }
        for (MonthlyCollectionNodeData row : collections) {
            collectionRows.deleteByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(
                    row.getCollectionPointType(), row.getCollectionPointId(), row.getYear(), row.getMonth());
        }
        var summaries = new ArrayList<com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary>();
        if (context == null) summaries.addAll(plan.nodeRows());
        for (YearMonth month : plan.months()) {
            if (context == null) {
                nodeRows.deleteByTemplateIdAndYearAndMonth(plan.templateId(), month.getYear(), month.getMonthValue());
            } else {
                var candidates = plan.nodeRows().stream().filter(row -> row.getYear() == month.getYear()
                        && row.getMonth() == month.getMonthValue()).toList();
                if (!sameNodeRows(nodeRows.findByTemplateIdAndYearAndMonth(
                        plan.templateId(), month.getYear(), month.getMonthValue()), candidates)) {
                    nodeRows.deleteByTemplateIdAndYearAndMonth(plan.templateId(), month.getYear(), month.getMonthValue());
                    summaries.addAll(candidates);
                }
            }
            if (publishCompany && (context == null || companies.stream().anyMatch(row ->
                    month.getYear() == row.getYear() && month.getMonthValue() == row.getMonth()))) {
                companyRows.deleteByCompanyDeptIdAndYearAndMonth(
                        plan.companyDeptId(), month.getYear(), month.getMonthValue());
            }
        }
        collectionRows.flush();
        nodeRows.flush();
        companyRows.flush();

        collectionRows.saveAll(collections);
        nodeRows.saveAll(summaries);
        companyRows.saveAll(companies);
        collectionRows.flush();
        nodeRows.flush();
        companyRows.flush();
        if (prediction != null && !companies.isEmpty()) {
            for (YearMonth month : plan.months()) {
                var rows = companies.stream().filter(row -> row.getYear() == month.getYear()
                        && row.getMonth() == month.getMonthValue()).toList();
                if (!rows.isEmpty()) {
                    prediction.record(plan.companyDeptId(), plan.templateId(), month, context == null ? 2 : 1, rows,
                            plan.collectionRows().stream().filter(row -> row.getYear() == month.getYear()
                                    && row.getMonth() == month.getMonthValue()).toList(),
                            context == null ? java.util.Set.of() : context.waitingPoints());
                }
            }
        }
    }

    private boolean canRepairCompany(MonthlyCompanyEnergySummary row, MonthlyRepairContext context) {
        if (!context.pastDeadline() && (!context.waitingPoints().isEmpty() || row.getResultStatus() != 1)) {
            return false;
        }
        return !companyRows.existsByCompanyDeptIdAndYearAndMonth(row.getCompanyDeptId(), row.getYear(), row.getMonth());
    }

    private boolean repairCollection(MonthlyCollectionNodeData row, MonthlyRepairContext context) {
        if (context.waitingPoints().contains(new MonthlyRepairContext.Point(
                row.getCollectionPointType(), row.getCollectionPointId()))) {
            return false;
        }
        return collectionRows.findByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(
                row.getCollectionPointType(), row.getCollectionPointId(), row.getYear(), row.getMonth())
                .map(old -> (!Integer.valueOf(1).equals(old.getDataStatus()) && Integer.valueOf(1).equals(row.getDataStatus()))
                        || Integer.valueOf(2).equals(old.getDataStatus())
                        && (!Objects.equals(old.getDataStatus(), row.getDataStatus())
                        || !Objects.equals(old.getDataMissingDescription(), row.getDataMissingDescription())))
                .orElse(true);
    }

    private static boolean sameNodeRows(List<com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary> old,
                                        List<com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary> candidates) {
        return old.stream().map(MonthlyPublicationWriter::nodeValues).collect(java.util.stream.Collectors.toSet())
                .equals(candidates.stream().map(MonthlyPublicationWriter::nodeValues)
                        .collect(java.util.stream.Collectors.toSet()));
    }

    private static List<?> nodeValues(com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary row) {
        return java.util.Arrays.asList(row.getSourceNodeId(), row.getParentSourceNodeId(), row.getNodeLevel(),
                row.getIsLeafCalcNode(), row.getEmissionCategory(), row.getEmissionSubcategory(), row.getResultStatus(),
                row.getMissingCollectionPointIds(), row.getSummarySource(), row.getCalculationUnitCode(),
                normalized(row.getDirectEnergyValue()), normalized(row.getDirectCarbonEmission()),
                normalized(row.getSubtotalEnergyValue()), normalized(row.getSubtotalCarbonEmission()),
                normalized(row.getCarbonEmissionFactor()));
    }

    private static java.math.BigDecimal normalized(java.math.BigDecimal value) {
        return value == null ? null : value.stripTrailingZeros();
    }

    private void lockTemplate(Long templateId) {
        List<Long> found = jdbc.queryForList(
                "select id from emission_template where id=? for update", Long.class, templateId);
        if (found.isEmpty()) {
            throw new IllegalStateException("核算模板不存在，templateId=" + templateId);
        }
    }

    private void lockPhysicalPoint(PointKey key) {
        String table = switch (key.type()) {
            case 1 -> "emission_meter_info";
            case 2 -> "emission_fossil_fuel_meter_info";
            case 3 -> "emission_purchased_heat_meter_info";
            default -> throw new IllegalArgumentException("不支持的采集点类型: " + key.type());
        };
        List<Long> found = jdbc.queryForList("select id from " + table + " where id=? for update",
                Long.class, key.id());
        if (found.isEmpty()) {
            throw new IllegalStateException("采集点不存在: type=" + key.type() + ", id=" + key.id());
        }
    }

    private record PointKey(Integer type, Long id) { }
}
