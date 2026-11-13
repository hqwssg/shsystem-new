package com.railway.carbon.platform.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.common.BizException;
import com.railway.carbon.platform.common.PageResult;
import com.railway.carbon.platform.dto.Dtos;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.sql.Date;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class DataService {

    private final JdbcTemplate jdbc;
    private final PredictionClient predictionClient;

    public DataService(JdbcTemplate jdbc, PredictionClient predictionClient) {
        this.jdbc = jdbc;
        this.predictionClient = predictionClient;
    }

    // ------------------------------------------------------------------
    // 活动数据
    // ------------------------------------------------------------------
    public PageResult<Dtos.ActivityRow> activity(String orgId, String varId,
                                                  String start, String end,
                                                  String qualityStatus,
                                                  int page, int size) {
        int p = Math.max(page, 1);
        int s = Math.min(Math.max(size, 1), 200);
        List<Object> args = new ArrayList<>();
        String where = buildActivityWhere(orgId, varId, start, end, qualityStatus, args);

        Long total = jdbc.queryForObject("SELECT COUNT(*) FROM prediction_activity_monthly a " + where,
                Long.class, args.toArray());
        List<Object> pageArgs = new ArrayList<>(args);
        pageArgs.add(s);
        pageArgs.add((p - 1) * s);
        String sql = """
                SELECT a.id, a.org_id, o.org_name, a.period, a.var_id, v.var_name,
                       a.value, a.reported_value, a.unit, a.source_status, a.is_estimated,
                       a.quality_status, a.data_flag, a.batch_id, a.data_version, a.created_at
                FROM prediction_activity_monthly a
                LEFT JOIN prediction_org o ON o.org_id = a.org_id
                LEFT JOIN prediction_energy_var v ON v.var_id = a.var_id
                """ + where + " ORDER BY a.period DESC, a.org_id, v.sort_order LIMIT ? OFFSET ?";
        List<Dtos.ActivityRow> rows = jdbc.query(sql, (rs, i) -> new Dtos.ActivityRow(
                rs.getLong("id"), rs.getString("org_id"), rs.getString("org_name"),
                toLocalDate(rs.getDate("period")), rs.getString("var_id"), rs.getString("var_name"),
                rs.getBigDecimal("value"), rs.getBigDecimal("reported_value"), rs.getString("unit"),
                rs.getString("source_status"), getBoolean(rs, "is_estimated"),
                rs.getString("quality_status"), rs.getString("data_flag"),
                rs.getString("batch_id"), rs.getString("data_version"),
                toLocalDateTime(rs.getTimestamp("created_at"))
        ), pageArgs.toArray());
        return new PageResult<>(rows, total == null ? 0 : total, p, s);
    }

    private String buildActivityWhere(String orgId, String varId, String start, String end,
                                      String qualityStatus, List<Object> args) {
        StringBuilder sb = new StringBuilder(" WHERE 1=1");
        if (orgId != null && !orgId.isBlank()) {
            sb.append(" AND a.org_id = ?");
            args.add(orgId);
        }
        if (varId != null && !varId.isBlank()) {
            sb.append(" AND a.var_id = ?");
            args.add(varId);
        }
        if (start != null && !start.isBlank()) {
            sb.append(" AND a.period >= ?");
            args.add(Date.valueOf(periodStart(start)));
        }
        if (end != null && !end.isBlank()) {
            sb.append(" AND a.period <= ?");
            args.add(Date.valueOf(periodEnd(end)));
        }
        if (qualityStatus != null && !qualityStatus.isBlank()) {
            sb.append(" AND a.quality_status = ?");
            args.add(qualityStatus);
        }
        return sb.toString();
    }

    /**
     * 查询指定分公司、指定月份的能耗数据。
     *
     * 返回活动数据（燃料/电力/热力）和当月排放结果，不含周转量、机车台数和 CO2 目标值。
     */
    public Dtos.MonthlyEnergy monthlyEnergy(String orgId, String period) {
        String periodDate = periodStart(period);
        LocalDate p = LocalDate.parse(periodDate);
        List<Dtos.Org> orgs = jdbc.query(
                "SELECT org_id, org_name, org_level, province FROM prediction_org WHERE org_id=?",
                (rs, i) -> new Dtos.Org(rs.getString("org_id"), rs.getString("org_name"),
                        rs.getInt("org_level"), rs.getString("province")), orgId);
        if (orgs.isEmpty()) {
            throw new BizException(HttpStatus.NOT_FOUND, "组织不存在：" + orgId);
        }
        String orgName = orgs.get(0).orgName();

        List<Dtos.EnergyItem> items = jdbc.query("""
                SELECT a.var_id, v.var_name, a.value, a.reported_value, a.unit,
                       a.source_status, a.is_estimated, a.quality_status, a.data_flag
                FROM prediction_activity_monthly a
                JOIN prediction_energy_var v ON v.var_id = a.var_id
                WHERE a.org_id = ? AND a.period = ?
                  AND v.var_category IN ('fuel', 'electricity', 'heat')
                ORDER BY v.sort_order
                """, (rs, i) -> new Dtos.EnergyItem(
                rs.getString("var_id"), rs.getString("var_name"),
                rs.getBigDecimal("value"), rs.getBigDecimal("reported_value"),
                rs.getString("unit"), rs.getString("source_status"),
                getBoolean(rs, "is_estimated"), rs.getString("quality_status"),
                rs.getString("data_flag")
        ), orgId, Date.valueOf(p));
        if (items.isEmpty()) {
            throw new BizException(HttpStatus.NOT_FOUND,
                    orgName + " " + period + " 无能耗数据");
        }

        Map<String, Integer> quality = new LinkedHashMap<>();
        quality.put("valid", 0);
        quality.put("pending", 0);
        quality.put("excluded", 0);
        for (Dtos.EnergyItem item : items) {
            quality.computeIfPresent(item.qualityStatus(), (k, v) -> v + 1);
        }
        String status = quality.get("pending") > 0 ? "pending_review"
                : (quality.get("excluded") > 0 ? "partial" : "valid");

        String batchId = jdbc.query("""
                SELECT batch_id FROM prediction_activity_monthly
                WHERE org_id=? AND period=? AND batch_id IS NOT NULL
                ORDER BY updated_at DESC LIMIT 1
                """, (rs, i) -> rs.getString("batch_id"), orgId, Date.valueOf(p))
                .stream().findFirst().orElse(null);

        Dtos.EnergyEmission emission = null;
        Map<String, Object> e = jdbc.query("""
                SELECT total_reported_tco2, total_comparable_tco2, electricity_factor,
                       heat_factor, factor_version, factor_source
                FROM prediction_emission_monthly
                WHERE org_id=? AND period=? AND scope='Total'
                """, (rs, i) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("total_reported_tco2", rs.getBigDecimal("total_reported_tco2"));
            m.put("total_comparable_tco2", rs.getBigDecimal("total_comparable_tco2"));
            m.put("electricity_factor", rs.getBigDecimal("electricity_factor"));
            m.put("heat_factor", rs.getBigDecimal("heat_factor"));
            m.put("factor_version", rs.getString("factor_version"));
            m.put("factor_source", rs.getString("factor_source"));
            return m;
        }, orgId, Date.valueOf(p)).stream().findFirst().orElse(null);
        if (e != null) {
            emission = new Dtos.EnergyEmission(
                    (BigDecimal) e.get("total_reported_tco2"),
                    (BigDecimal) e.get("total_comparable_tco2"),
                    (BigDecimal) e.get("electricity_factor"),
                    (BigDecimal) e.get("heat_factor"),
                    (String) e.get("factor_version"),
                    (String) e.get("factor_source"));
        }

        return new Dtos.MonthlyEnergy(
                orgId, orgName, p, p.toString().substring(0, 7), status,
                batchId, quality, items, emission);
    }

    /**
     * 比较指定分公司、月份、能耗品类的提交值与库中 value。
     *
     * @return 1=存在且相等，0=存在但不相等，2=记录不存在
     */
    public Dtos.EnergyCompareResult compareEnergy(String orgId, String period,
                                                  String varId, BigDecimal inputValue) {
        String periodDate = periodStart(period);
        LocalDate p = LocalDate.parse(periodDate);
        String normalizedVar = varId == null ? "" : varId.trim().toUpperCase();
        List<BigDecimal> values = jdbc.query("""
                SELECT a.value
                FROM prediction_activity_monthly a
                JOIN prediction_energy_var v ON v.var_id = a.var_id
                WHERE a.org_id = ? AND a.period = ? AND a.var_id = ?
                  AND v.var_category IN ('fuel', 'electricity', 'heat')
                """, (rs, i) -> rs.getBigDecimal("value"),
                orgId, Date.valueOf(p), normalizedVar);
        if (values.isEmpty()) {
            return new Dtos.EnergyCompareResult(2, false, false, orgId,
                    p.toString().substring(0, 7), normalizedVar, inputValue, null,
                    "记录不存在");
        }
        BigDecimal stored = values.get(0);
        boolean equal = stored != null && inputValue != null && stored.compareTo(inputValue) == 0;
        return new Dtos.EnergyCompareResult(equal ? 1 : 0, true, equal, orgId,
                p.toString().substring(0, 7), normalizedVar, inputValue, stored,
                equal ? "值相等" : "值不相等");
    }

    public JsonNode ingest(Dtos.IngestRequest request) {
        Map<String, Object> body = new HashMap<>();
        String operator = blank(request.operator()) ? "platform" : request.operator();
        String key = blank(request.idempotencyKey())
                ? "PLT-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + "-" + UUID.randomUUID().toString().substring(0, 6)
                : request.idempotencyKey();
        body.put("operator", operator);
        body.put("idempotency_key", key);
        body.put("run_anomaly", request.runAnomaly() == null || request.runAnomaly());
        body.put("override", Boolean.TRUE.equals(request.override()));
        if (!blank(request.factorVersion())) {
            body.put("factor_version", request.factorVersion());
        }
        if (!blank(request.overrideReason())) {
            body.put("override_reason", request.overrideReason());
        }
        List<Map<String, Object>> records = new ArrayList<>();
        for (Dtos.IngestRecord r : request.records()) {
            Map<String, Object> m = new HashMap<>();
            m.put("org_id", r.orgId());
            m.put("period", r.period());
            m.put("var_id", r.varId());
            m.put("value", r.value());
            if (r.reportedValue() != null) {
                m.put("reported_value", r.reportedValue());
            }
            if (!blank(r.unit())) {
                m.put("unit", r.unit());
            }
            records.add(m);
        }
        body.put("records", records);
        return predictionClient.ingest(body);
    }

    // ------------------------------------------------------------------
    // 排放因子
    // ------------------------------------------------------------------
    public List<Dtos.FactorRow> factors(String varId) {
        List<Object> args = new ArrayList<>();
        String where = "";
        if (!blank(varId)) {
            where = " WHERE f.var_id = ?";
            args.add(varId);
        }
        String sql = """
                SELECT f.factor_id, f.var_id, v.var_name, f.factor_value, f.factor_unit,
                       f.factor_version, f.effective_from, f.effective_to,
                       f.factor_source, f.is_caliber_change, f.policy_basis
                FROM prediction_emission_factor f
                LEFT JOIN prediction_energy_var v ON v.var_id = f.var_id
                """ + where + " ORDER BY f.var_id, f.effective_from DESC";
        return jdbc.query(sql, (rs, i) -> new Dtos.FactorRow(
                rs.getLong("factor_id"), rs.getString("var_id"), rs.getString("var_name"),
                rs.getBigDecimal("factor_value"), rs.getString("factor_unit"),
                rs.getString("factor_version"), toLocalDate(rs.getDate("effective_from")),
                toLocalDate(rs.getDate("effective_to")), rs.getString("factor_source"),
                getBoolean(rs, "is_caliber_change"), rs.getString("policy_basis")
        ), args.toArray());
    }

    @Transactional
    public Dtos.FactorRow createFactor(Dtos.FactorRequest req) {
        if (req.effectiveTo() != null && req.effectiveTo().isBefore(req.effectiveFrom())) {
            throw new BizException("失效日期不能早于生效日期");
        }
        // 新增晚于当前版本的因子时，自动把上一条长期有效因子截止到新版本前一天。
        // 这样 2025→2026 的年度因子切换不需要用户手工改历史记录。
        List<Map<String, Object>> openPrev = jdbc.queryForList("""
                SELECT factor_id, effective_from
                FROM prediction_emission_factor
                WHERE var_id = ? AND effective_from < ? AND effective_to IS NULL
                ORDER BY effective_from DESC LIMIT 1
                """, req.varId(), Date.valueOf(req.effectiveFrom()));
        if (!openPrev.isEmpty()) {
            jdbc.update("UPDATE prediction_emission_factor SET effective_to = ? WHERE factor_id = ?",
                    Date.valueOf(req.effectiveFrom().minusDays(1)),
                    openPrev.get(0).get("factor_id"));
        }
        List<Map<String, Object>> overlaps = jdbc.queryForList("""
                SELECT factor_id, effective_from
                FROM prediction_emission_factor
                WHERE var_id = ? AND effective_from <= ?
                  AND (effective_to IS NULL OR effective_to >= ?)
                """, req.varId(), Date.valueOf(req.effectiveTo() == null ? LocalDate.of(9999, 12, 31) : req.effectiveTo()),
                Date.valueOf(req.effectiveFrom()));
        boolean conflict = overlaps.stream().anyMatch(r ->
                !toLocalDate(r.get("effective_from")).equals(req.effectiveFrom()));
        if (conflict) {
            throw new BizException(HttpStatus.CONFLICT,
                    req.varId() + " 在 " + req.effectiveFrom() + " 起的生效期与已有因子重叠");
        }
        jdbc.update("""
                INSERT INTO prediction_emission_factor
                  (var_id, factor_value, factor_unit, factor_version, effective_from,
                   effective_to, factor_source, is_caliber_change, policy_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                  factor_value = VALUES(factor_value),
                  factor_unit = VALUES(factor_unit),
                  factor_version = VALUES(factor_version),
                  effective_to = VALUES(effective_to),
                  factor_source = VALUES(factor_source),
                  is_caliber_change = VALUES(is_caliber_change),
                  policy_basis = VALUES(policy_basis)
                """, req.varId(), req.factorValue(), req.factorUnit(), req.factorVersion(),
                Date.valueOf(req.effectiveFrom()),
                req.effectiveTo() == null ? null : Date.valueOf(req.effectiveTo()),
                req.factorSource(), Boolean.TRUE.equals(req.caliberChange()) ? 1 : 0,
                req.policyBasis());
        return factors(req.varId()).stream()
                .filter(x -> req.effectiveFrom().equals(x.effectiveFrom()))
                .findFirst()
                .orElseThrow(() -> new BizException("因子写入后查询失败"));
    }

    // ------------------------------------------------------------------
    // 口径规则（供热面积系数 / 电网因子）
    // ------------------------------------------------------------------
    public List<Dtos.CaliberRuleRow> caliberRules(String orgId, String ruleType) {
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (!blank(orgId)) {
            where.append(" AND (r.org_id = ? OR r.org_id = 'ALL')");
            args.add(orgId);
        }
        if (!blank(ruleType)) {
            where.append(" AND r.rule_type = ?");
            args.add(ruleType);
        }
        String sql = """
                SELECT r.rule_id, r.org_id, o.org_name, r.rule_type, r.effective_from,
                       r.effective_to, r.rule_value, r.unit, r.rule_version, r.source, r.note
                FROM prediction_caliber_rule r
                LEFT JOIN prediction_org o ON o.org_id = r.org_id
                """ + where + " ORDER BY r.rule_type, r.org_id, r.effective_from DESC";
        return jdbc.query(sql, (rs, i) -> new Dtos.CaliberRuleRow(
                rs.getString("rule_id"), rs.getString("org_id"), rs.getString("org_name"),
                rs.getString("rule_type"), toLocalDate(rs.getDate("effective_from")),
                toLocalDate(rs.getDate("effective_to")), rs.getBigDecimal("rule_value"),
                rs.getString("unit"), rs.getString("rule_version"),
                rs.getString("source"), rs.getString("note")
        ), args.toArray());
    }

    @Transactional
    public Dtos.CaliberRuleRow saveCaliberRule(Dtos.CaliberRuleRequest req) {
        if (req.effectiveTo() != null && req.effectiveTo().isBefore(req.effectiveFrom())) {
            throw new BizException("失效日期不能早于生效日期");
        }
        List<Map<String, Object>> openPrev = jdbc.queryForList("""
                SELECT rule_id FROM prediction_caliber_rule
                WHERE org_id = ? AND rule_type = ? AND effective_from < ? AND effective_to IS NULL
                ORDER BY effective_from DESC LIMIT 1
                """, req.orgId(), req.ruleType(), Date.valueOf(req.effectiveFrom()));
        if (!openPrev.isEmpty()) {
            jdbc.update("UPDATE prediction_caliber_rule SET effective_to = ? WHERE rule_id = ?",
                    Date.valueOf(req.effectiveFrom().minusDays(1)), openPrev.get(0).get("rule_id"));
        }
        List<Map<String, Object>> overlaps = jdbc.queryForList("""
                SELECT rule_id FROM prediction_caliber_rule
                WHERE org_id = ? AND rule_type = ? AND effective_from <= ?
                  AND (effective_to IS NULL OR effective_to >= ?)
                """, req.orgId(), req.ruleType(),
                Date.valueOf(req.effectiveTo() == null ? LocalDate.of(9999, 12, 31) : req.effectiveTo()),
                Date.valueOf(req.effectiveFrom()));
        boolean conflict = overlaps.stream().anyMatch(r -> !req.ruleId().equals(r.get("rule_id")));
        if (conflict) {
            throw new BizException(HttpStatus.CONFLICT, "该组织同类口径规则的生效期与已有规则重叠");
        }
        jdbc.update("""
                INSERT INTO prediction_caliber_rule
                  (rule_id, org_id, rule_type, effective_from, effective_to, rule_value,
                   unit, rule_version, source, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                  org_id = VALUES(org_id), rule_type = VALUES(rule_type),
                  effective_from = VALUES(effective_from), effective_to = VALUES(effective_to),
                  rule_value = VALUES(rule_value), unit = VALUES(unit),
                  rule_version = VALUES(rule_version), source = VALUES(source), note = VALUES(note)
                """, req.ruleId(), req.orgId(), req.ruleType(), Date.valueOf(req.effectiveFrom()),
                req.effectiveTo() == null ? null : Date.valueOf(req.effectiveTo()),
                req.ruleValue(), req.unit(), req.ruleVersion(), req.source(), req.note());
        return caliberRules(req.orgId(), req.ruleType()).stream()
                .filter(x -> req.ruleId().equals(x.ruleId()))
                .findFirst().orElseThrow(() -> new BizException("口径规则写入后查询失败"));
    }

    // ------------------------------------------------------------------
    // 政策/外部因子
    // ------------------------------------------------------------------
    public PageResult<Dtos.PolicyFactorRow> policyFactors(String category, String start,
                                                           String end, int page, int size) {
        int p = Math.max(page, 1);
        int s = Math.min(Math.max(size, 1), 500);
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (!blank(category)) {
            where.append(" AND category = ?");
            args.add(category);
        }
        if (!blank(start)) {
            where.append(" AND period >= ?");
            args.add(Date.valueOf(periodStart(start)));
        }
        if (!blank(end)) {
            where.append(" AND period <= ?");
            args.add(Date.valueOf(periodEnd(end)));
        }
        Long total = jdbc.queryForObject("SELECT COUNT(*) FROM prediction_policy_factor" + where,
                Long.class, args.toArray());
        List<Object> pageArgs = new ArrayList<>(args);
        pageArgs.add(s);
        pageArgs.add((p - 1) * s);
        String sql = """
                SELECT id, factor_id, factor_name, period, value, unit, category,
                       source_level, source_status, is_scenario_only, data_source
                FROM prediction_policy_factor
                """ + where + " ORDER BY period DESC, factor_id LIMIT ? OFFSET ?";
        List<Dtos.PolicyFactorRow> rows = jdbc.query(sql, (rs, i) -> new Dtos.PolicyFactorRow(
                rs.getLong("id"), rs.getString("factor_id"), rs.getString("factor_name"),
                toLocalDate(rs.getDate("period")), rs.getBigDecimal("value"), rs.getString("unit"),
                rs.getString("category"), rs.getString("source_level"), rs.getString("source_status"),
                getBoolean(rs, "is_scenario_only"), rs.getString("data_source")
        ), pageArgs.toArray());
        return new PageResult<>(rows, total == null ? 0 : total, p, s);
    }

    @Transactional
    public int savePolicyFactors(List<Dtos.PolicyFactorRequest> factors) {
        int n = 0;
        for (Dtos.PolicyFactorRequest f : factors) {
            n += jdbc.update("""
                    INSERT INTO prediction_policy_factor
                      (factor_id, factor_name, period, value, unit, category,
                       source_level, source_status, is_scenario_only, data_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                      factor_name = VALUES(factor_name), value = VALUES(value),
                      unit = VALUES(unit), category = VALUES(category),
                      source_level = VALUES(source_level), source_status = VALUES(source_status),
                      is_scenario_only = VALUES(is_scenario_only), data_source = VALUES(data_source)
                    """, f.factorId(), f.factorName(), Date.valueOf(periodStart(f.period())),
                    f.value(), f.unit(), blank(f.category()) ? "policy" : f.category(),
                    blank(f.sourceLevel()) ? "national" : f.sourceLevel(),
                    blank(f.sourceStatus()) ? "原始" : f.sourceStatus(),
                    Boolean.TRUE.equals(f.scenarioOnly()) ? 1 : 0, f.dataSource());
        }
        return n;
    }

    // ------------------------------------------------------------------
    // 日历事件
    // ------------------------------------------------------------------
    public List<Dtos.CalendarEventRow> calendarEvents() {
        return jdbc.query("""
                SELECT id, event_id, event_type, event_name, start_date, end_date, org_id,
                       impact_direction, source, note
                FROM prediction_calendar_event
                ORDER BY start_date DESC, id DESC
                """, (rs, i) -> new Dtos.CalendarEventRow(
                rs.getLong("id"), rs.getString("event_id"), rs.getString("event_type"),
                rs.getString("event_name"), toLocalDate(rs.getDate("start_date")),
                toLocalDate(rs.getDate("end_date")), rs.getString("org_id"),
                rs.getString("impact_direction"), rs.getString("source"), rs.getString("note")
        ));
    }

    @Transactional
    public Dtos.CalendarEventRow saveCalendarEvent(Dtos.CalendarEventRequest req) {
        if (req.endDate().isBefore(req.startDate())) {
            throw new BizException("结束日期不能早于开始日期");
        }
        String org = blank(req.orgId()) ? "ALL" : req.orgId();
        String direction = blank(req.impactDirection()) ? "unknown" : req.impactDirection();
        if (req.eventId() != null && jdbc.queryForObject(
                "SELECT COUNT(*) FROM prediction_calendar_event WHERE event_id = ?",
                Long.class, req.eventId()) > 0) {
            jdbc.update("""
                    UPDATE prediction_calendar_event
                    SET event_type = ?, event_name = ?, start_date = ?, end_date = ?,
                        org_id = ?, impact_direction = ?, source = ?, note = ?
                    WHERE event_id = ?
                    """, req.eventType(), req.eventName(), Date.valueOf(req.startDate()),
                    Date.valueOf(req.endDate()), org, direction, req.source(), req.note(),
                    req.eventId());
        } else {
            jdbc.update("""
                    INSERT INTO prediction_calendar_event
                      (event_id, event_type, event_name, start_date, end_date, org_id,
                       impact_direction, source, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, req.eventId(), req.eventType(), req.eventName(),
                    Date.valueOf(req.startDate()), Date.valueOf(req.endDate()),
                    org, direction, req.source(), req.note());
        }
        return calendarEvents().stream()
                .filter(x -> req.eventId().equals(x.eventId()))
                .findFirst().orElseThrow(() -> new BizException("日历事件写入后查询失败"));
    }

    public int deleteCalendarEvent(long id) {
        return jdbc.update("DELETE FROM prediction_calendar_event WHERE id = ?", id);
    }

    // ------------------------------------------------------------------
    // 工具
    // ------------------------------------------------------------------
    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }

    private static String periodStart(String period) {
        if (period == null || period.isBlank()) {
            throw new BizException("月份不能为空");
        }
        String value = period.length() == 7 ? period + "-01" : period;
        try {
            return LocalDate.parse(value).withDayOfMonth(1).toString();
        } catch (Exception ex) {
            throw new BizException("月份格式不正确：" + period);
        }
    }

    private static String periodEnd(String period) {
        if (period == null || period.isBlank()) {
            throw new BizException("月份不能为空");
        }
        String value = period.length() == 7 ? period + "-01" : period;
        try {
            return LocalDate.parse(value).withDayOfMonth(1).plusMonths(1).minusDays(1).toString();
        } catch (Exception ex) {
            throw new BizException("月份格式不正确：" + period);
        }
    }

    private static LocalDate toLocalDate(Date date) {
        return date == null ? null : date.toLocalDate();
    }

    private static LocalDate toLocalDate(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Date d) {
            return d.toLocalDate();
        }
        if (value instanceof LocalDate d) {
            return d;
        }
        return LocalDate.parse(value.toString());
    }

    private static LocalDateTime toLocalDateTime(java.sql.Timestamp ts) {
        return ts == null ? null : ts.toLocalDateTime();
    }

    private static Boolean getBoolean(ResultSet rs, String column) throws SQLException {
        Object value = rs.getObject(column);
        if (value == null) {
            return null;
        }
        if (value instanceof Boolean b) {
            return b;
        }
        return ((Number) value).intValue() != 0;
    }
}
