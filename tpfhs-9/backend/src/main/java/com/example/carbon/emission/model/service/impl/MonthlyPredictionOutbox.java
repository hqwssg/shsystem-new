package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.YearMonth;
import java.time.ZoneId;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/** The publication and its immutable delivery input are committed together. */
@Service
public class MonthlyPredictionOutbox {
    private static final String CONFIG_KEY = "carbon.trend-prediction.auto-ingest-company-monthly-data";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final FactorDimensionService factors;

    public MonthlyPredictionOutbox(JdbcTemplate jdbc, ObjectMapper json, FactorDimensionService factors) {
        this.jdbc = jdbc;
        this.json = json;
        this.factors = factors;
    }

    boolean enabled() {
        return Boolean.TRUE.equals(jdbc.query("select config_value from sys_config where config_key=? "
                + "order by config_id desc limit 1", rs -> rs.next() && "true".equalsIgnoreCase(rs.getString(1)), CONFIG_KEY));
    }

    private String lockCompany(long company) {
        return jdbc.query("select config_value from sys_config where config_key=? order by config_id desc limit 1 for update",
                rs -> rs.next() ? rs.getString(1) : null, StatisticsBaselineTemplateService.KEY_PREFIX + company);
    }

    boolean lockBaseline(Long company, Long template) {
        String value = company == null ? null : lockCompany(company);
        return value != null && String.valueOf(template).equals(value.trim());
    }

    void record(long company, long template, YearMonth month, int type, List<MonthlyCompanyEnergySummary> companies,
                List<MonthlyCollectionNodeData> points, Set<MonthlyRepairContext.Point> waiting) {
        List<Group> groups = companies.stream().map(row -> new Group(row.getId(), row.getEnergyCategoryL1(),
                row.getEmissionSubcategory(), row.getCalculationUnitCode(), row.getStandardEnergyValue())).toList();
        List<Missing> missing = points.stream().filter(row -> waiting.contains(key(row))
                        || !Integer.valueOf(1).equals(row.getDataStatus()))
                .map(row -> new Missing(row.getCollectionPointType(), row.getCollectionPointId(), row.getEnergyCategoryL1().trim(),
                        factors.resolveSubcategoryCode(row.getEmissionSubcategory()),
                        waiting.contains(key(row)) ? 2 : row.getDataStatus(),
                        waiting.contains(key(row)) || row.getAdjustedEnergyValue() == null
                        || Integer.valueOf(2).equals(row.getDataStatus()))).toList();
        boolean complete = companies.stream().allMatch(row -> Integer.valueOf(1).equals(row.getResultStatus()));
        Instant now = Instant.now();
        Instant deadline = month.plusMonths(1).atDay(26).atStartOfDay(ZoneId.of(MonthlyRepairService.ZONE)).toInstant();
        jdbc.update("update emission_monthly_prediction_outbox set delivery_status='SUPERSEDED' "
                        + "where company_dept_id=? and period=? and delivery_status in ('QUEUED','RETRY','BLOCKED')",
                company, month.atDay(1));
        jdbc.update("insert into emission_monthly_prediction_outbox "
                        + "(company_dept_id,template_id,period,operation_type,snapshot,delivery_status,next_attempt_at) "
                        + "values (?,?,?,?,?,?,?)", company, template, month.atDay(1), type,
                encode(new Snapshot(groups, missing, complete)), enabled() ? "QUEUED" : "DISABLED",
                Timestamp.from(!complete && now.isBefore(deadline) ? deadline : now));
    }

    private MonthlyRepairContext.Point key(MonthlyCollectionNodeData row) {
        return new MonthlyRepairContext.Point(row.getCollectionPointType(), row.getCollectionPointId());
    }

    List<Long> due() {
        return jdbc.queryForList("select id from emission_monthly_prediction_outbox "
                + "where (delivery_status in ('QUEUED','RETRY') and next_attempt_at<=current_timestamp) "
                + "or (delivery_status='SENDING' and lease_until<=current_timestamp) order by id limit 30", Long.class);
    }

    @Transactional
    public Delivery claim(long id) {
        Delivery job = read(id);
        if (job == null) return null;
        if (!lockBaseline(job.company(), job.template()) || !isLatest(job)) {
            jdbc.update("update emission_monthly_prediction_outbox set delivery_status='SUPERSEDED' where id=? "
                    + "and (delivery_status in ('QUEUED','RETRY') or (delivery_status='SENDING' "
                    + "and lease_until<=current_timestamp))", id);
            return null;
        }
        Boolean active = jdbc.query("select id from emission_monthly_prediction_outbox "
                        + "where company_dept_id=? and period=? and delivery_status='SENDING' and lease_until>current_timestamp "
                        + "limit 1 for update", rs -> { return rs.next(); }, job.company(), job.month().atDay(1));
        if (Boolean.TRUE.equals(active)) return null;
        int changed = jdbc.update("update emission_monthly_prediction_outbox set delivery_status='SENDING', "
                        + "attempt_count=attempt_count+1,lease_until=timestampadd(minute,5,current_timestamp) where id=? "
                        + "and ((delivery_status in ('QUEUED','RETRY') and next_attempt_at<=current_timestamp) "
                        + "or (delivery_status='SENDING' and lease_until<=current_timestamp))", id);
        return changed == 1 ? read(id) : null;
    }

    boolean freeze(Delivery job, String payload) {
        return jdbc.update("update emission_monthly_prediction_outbox set request_payload=? where id=? "
                        + "and delivery_status='SENDING' and attempt_count=? and request_payload is null",
                payload, job.id(), job.attempt()) == 1;
    }

    @Transactional
    public void finish(Delivery job, String status, String batch, String reason) {
        boolean latest = lockBaseline(job.company(), job.template()) && isLatest(job);
        int updated = jdbc.update("update emission_monthly_prediction_outbox set delivery_status=?,batch_id=?,"
                        + "last_error=?,lease_until=null,next_attempt_at=timestampadd(minute,?,current_timestamp) "
                        + "where id=? and delivery_status='SENDING' and attempt_count=?",
                latest ? status : "SUPERSEDED", batch, reason, Math.min(60, 1 << Math.min(6, job.attempt())),
                job.id(), job.attempt());
        if (updated == 0 || !latest) return;
        int ingestStatus = switch (status) {
            case "COMPLETED", "PENDING_REVIEW", "UNCHANGED" -> 1;
            case "RETRY", "BLOCKED" -> 2;
            default -> 0;
        };
        for (Group group : job.snapshot().groups()) {
            jdbc.update("update emission_company_energy_summary_month set ingest_status=? "
                            + "where id=? and company_dept_id=? and year=? and month=?", ingestStatus, group.id(),
                    job.company(), job.month().getYear(), job.month().getMonthValue());
        }
    }

    private boolean isLatest(Delivery job) {
        Long latest = jdbc.query("select id from emission_monthly_prediction_outbox where company_dept_id=? "
                        + "and period=? order by id desc limit 1 for update", rs -> rs.next() ? rs.getLong(1) : null,
                job.company(), job.month().atDay(1));
        return Objects.equals(latest, job.id());
    }

    private Delivery read(long id) {
        return jdbc.query("select * from emission_monthly_prediction_outbox where id=?", rs -> rs.next()
                ? new Delivery(id, rs.getLong("company_dept_id"), rs.getLong("template_id"),
                YearMonth.from(rs.getDate("period").toLocalDate()),
                rs.getInt("operation_type"), decode(rs.getString("snapshot")), rs.getString("request_payload"),
                rs.getInt("attempt_count")) : null, id);
    }

    private Snapshot decode(String value) {
        try { return json.readValue(value, Snapshot.class); }
        catch (JsonProcessingException e) { throw new IllegalStateException("月度发送快照无法读取", e); }
    }

    String encode(Object value) {
        try { return json.writeValueAsString(value); }
        catch (JsonProcessingException e) { throw new IllegalStateException("月度发送快照无法序列化", e); }
    }

    record Delivery(long id, long company, long template, YearMonth month, int type, Snapshot snapshot, String request, int attempt) {}
    record Snapshot(List<Group> groups, List<Missing> missing, boolean complete) {}
    record Group(long id, String category, String subcategory, String unit, BigDecimal value) {}
    record Missing(int type, long id, String category, String subcategory, Integer status, boolean noValue) {}
}
