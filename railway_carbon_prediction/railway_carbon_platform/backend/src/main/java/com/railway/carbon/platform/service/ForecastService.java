package com.railway.carbon.platform.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.dto.Dtos;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Date;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class ForecastService {

    private final JdbcTemplate jdbc;
    private final PredictionClient predictionClient;

    public ForecastService(JdbcTemplate jdbc, PredictionClient predictionClient) {
        this.jdbc = jdbc;
        this.predictionClient = predictionClient;
    }

    public List<Dtos.ForecastRow> forecast(String orgId, String scenario,
                                           String start, String end) {
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (orgId != null && !orgId.isBlank()) {
            where.append(" AND f.org_id = ?");
            args.add(orgId);
        }
        if (scenario != null && !scenario.isBlank()) {
            where.append(" AND f.scenario = ?");
            args.add(scenario);
        }
        if (start != null && !start.isBlank()) {
            where.append(" AND f.period >= ?");
            args.add(Date.valueOf(periodStart(start)));
        }
        if (end != null && !end.isBlank()) {
            where.append(" AND f.period <= ?");
            args.add(Date.valueOf(periodEnd(end)));
        }
        String sql = """
                SELECT f.id, f.model_id, f.org_id, o.org_name, f.period, f.scenario,
                       f.target_var, f.point, f.lower_bound, f.upper_bound, f.reported_point,
                       f.comparable_point, f.confidence_level, f.created_at
                FROM prediction_forecast f
                LEFT JOIN prediction_org o ON o.org_id = f.org_id
                """ + where + " ORDER BY f.org_id, f.period";
        return jdbc.query(sql, (rs, i) -> new Dtos.ForecastRow(
                rs.getLong("id"), rs.getString("model_id"), rs.getString("org_id"),
                rs.getString("org_name"), toLocalDate(rs.getDate("period")),
                rs.getString("scenario"), rs.getString("target_var"),
                rs.getBigDecimal("point"), rs.getBigDecimal("lower_bound"),
                rs.getBigDecimal("upper_bound"), rs.getBigDecimal("reported_point"),
                rs.getBigDecimal("comparable_point"), rs.getBigDecimal("confidence_level"),
                toLocalDateTime(rs.getTimestamp("created_at"))
        ), args.toArray());
    }

    public List<Dtos.HistoryRow> history(String orgId, String start, String end) {
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (orgId != null && !orgId.isBlank()) {
            where.append(" AND e.org_id = ?");
            args.add(orgId);
        }
        if (start != null && !start.isBlank()) {
            where.append(" AND e.period >= ?");
            args.add(Date.valueOf(periodStart(start)));
        }
        if (end != null && !end.isBlank()) {
            where.append(" AND e.period <= ?");
            args.add(Date.valueOf(periodEnd(end)));
        }
        String sql = """
                SELECT e.org_id, o.org_name, e.period, e.total_reported_tco2,
                       e.total_comparable_tco2, e.electricity_factor, e.heat_factor,
                       e.factor_version
                FROM prediction_emission_monthly e
                LEFT JOIN prediction_org o ON o.org_id = e.org_id
                """ + where + " ORDER BY e.org_id, e.period";
        return jdbc.query(sql, (rs, i) -> new Dtos.HistoryRow(
                rs.getString("org_id"), rs.getString("org_name"),
                toLocalDate(rs.getDate("period")), rs.getBigDecimal("total_reported_tco2"),
                rs.getBigDecimal("total_comparable_tco2"), rs.getBigDecimal("electricity_factor"),
                rs.getBigDecimal("heat_factor"), rs.getString("factor_version")
        ), args.toArray());
    }

    public JsonNode generate(Dtos.ForecastGenerateRequest req) {
        Map<String, Object> body = new HashMap<>();
        body.put("org_ids", req.orgIds() == null || req.orgIds().isEmpty()
                ? List.of("JLG", "SNF", "YPF") : req.orgIds());
        body.put("horizon", req.horizon() == null ? 12 : req.horizon());
        body.put("scenario", req.scenario() == null ? "BAU" : req.scenario());
        if (req.asOf() != null && !req.asOf().isBlank()) {
            body.put("as_of", req.asOf());
        }
        body.put("write_db", req.writeDb() == null || req.writeDb());
        body.put("operator", req.operator() == null ? "platform" : req.operator());
        body.put("async_run", Boolean.TRUE.equals(req.asyncRun()));
        return predictionClient.generateForecast(body);
    }

    public List<Dtos.DashboardSummary> dashboard() {
        List<Dtos.DashboardSummary> out = new ArrayList<>();
        jdbc.query("SELECT org_id, org_name FROM prediction_org WHERE status='active' ORDER BY org_level, org_id",
                rs -> {
                    String orgId = rs.getString("org_id");
                    String orgName = rs.getString("org_name");
                    Map<String, Object> latest = jdbc.query(
                            "SELECT period,total_reported_tco2,total_comparable_tco2 FROM prediction_emission_monthly "
                                    + "WHERE org_id=? ORDER BY period DESC LIMIT 1",
                            (r, i) -> {
                                Map<String, Object> m = new HashMap<>();
                                m.put("period", r.getDate("period"));
                                m.put("totalReportedTco2", r.getBigDecimal("total_reported_tco2"));
                                m.put("totalComparableTco2", r.getBigDecimal("total_comparable_tco2"));
                                return m;
                            }, orgId).stream().findFirst().orElse(null);
                    Map<String, Object> fc = jdbc.queryForMap(
                            "SELECT COUNT(*) AS n, COALESCE(SUM(point),0) AS point, "
                                    + "COALESCE(SUM(reported_point),0) AS reported FROM prediction_forecast "
                                    + "WHERE org_id=? AND scenario='BAU'", orgId);
                    Integer pending = jdbc.queryForObject(
                            "SELECT COUNT(*) FROM prediction_anomaly WHERE org_id=? AND status='pending'",
                            Integer.class, orgId);
                    out.add(new Dtos.DashboardSummary(orgId, orgName, latest, fc,
                            pending == null ? 0 : pending));
                });
        return out;
    }

    private static LocalDate toLocalDate(Date date) {
        return date == null ? null : date.toLocalDate();
    }

    private static LocalDateTime toLocalDateTime(java.sql.Timestamp ts) {
        return ts == null ? null : ts.toLocalDateTime();
    }

    private static String periodStart(String period) {
        String v = period.length() == 7 ? period + "-01" : period;
        return LocalDate.parse(v).withDayOfMonth(1).toString();
    }

    private static String periodEnd(String period) {
        String v = period.length() == 7 ? period + "-01" : period;
        return LocalDate.parse(v).withDayOfMonth(1).plusMonths(1).minusDays(1).toString();
    }
}
