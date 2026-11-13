package com.railway.carbon.platform.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.common.BizException;
import com.railway.carbon.platform.common.PageResult;
import com.railway.carbon.platform.dto.Dtos;
import org.springframework.http.HttpStatus;
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
public class AnomalyService {

    private final JdbcTemplate jdbc;
    private final PredictionClient predictionClient;

    public AnomalyService(JdbcTemplate jdbc, PredictionClient predictionClient) {
        this.jdbc = jdbc;
        this.predictionClient = predictionClient;
    }

    public PageResult<Dtos.AnomalyRow> list(String scope, String status, String orgId,
                                            String level, String start, String end,
                                            int page, int size) {
        int p = Math.max(page, 1);
        int s = Math.min(Math.max(size, 1), 500);
        boolean watch = "watch".equalsIgnoreCase(scope);
        String table = watch ? "prediction_anomaly_watch" : "prediction_anomaly";
        String alias = "a";
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (!watch && status != null && !status.isBlank()) {
            where.append(" AND a.status = ?");
            args.add(status);
        }
        if (orgId != null && !orgId.isBlank()) {
            where.append(" AND a.org_id = ?");
            args.add(orgId);
        }
        if (level != null && !level.isBlank()) {
            where.append(" AND a.level = ?");
            args.add(level);
        }
        if (start != null && !start.isBlank()) {
            where.append(" AND a.period >= ?");
            args.add(Date.valueOf(periodStart(start)));
        }
        if (end != null && !end.isBlank()) {
            where.append(" AND a.period <= ?");
            args.add(Date.valueOf(periodEnd(end)));
        }
        Long total = jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " a" + where,
                Long.class, args.toArray());
        List<Object> pageArgs = new ArrayList<>(args);
        pageArgs.add(s);
        pageArgs.add((p - 1) * s);
        String sql = "SELECT " + columns(watch) + " FROM " + table + " a "
                + "LEFT JOIN prediction_org o ON o.org_id = a.org_id "
                + "LEFT JOIN prediction_energy_var v ON v.var_id = a.var_id "
                + where + " ORDER BY a.period DESC, a.id DESC LIMIT ? OFFSET ?";
        List<Dtos.AnomalyRow> rows = jdbc.query(sql, (rs, i) -> mapRow(rs, watch), pageArgs.toArray());
        return new PageResult<>(rows, total == null ? 0 : total, p, s);
    }

    public Dtos.AnomalyRow detail(long id, String scope) {
        boolean watch = "watch".equalsIgnoreCase(scope);
        String table = watch ? "prediction_anomaly_watch" : "prediction_anomaly";
        String sql = "SELECT " + columns(watch) + " FROM " + table + " a "
                + "LEFT JOIN prediction_org o ON o.org_id = a.org_id "
                + "LEFT JOIN prediction_energy_var v ON v.var_id = a.var_id WHERE a.id = ?";
        List<Dtos.AnomalyRow> rows = jdbc.query(sql, (rs, i) -> mapRow(rs, watch), id);
        if (rows.isEmpty()) {
            throw new BizException(HttpStatus.NOT_FOUND, "异常记录不存在");
        }
        return rows.get(0);
    }

    public JsonNode review(long id, Dtos.ReviewRequest req) {
        Map<String, Object> body = new HashMap<>();
        body.put("action", req.action());
        body.put("correction_value", req.correctionValue());
        body.put("reviewer", req.reviewer());
        body.put("note", req.note());
        return predictionClient.review(id, body);
    }

    private String columns(boolean watch) {
        if (watch) {
            return """
                    a.id, a.org_id, o.org_name, a.period, a.var_id, v.var_name,
                    a.level, a.category, a.score, NULL AS confidence, NULL AS channel,
                    a.channels, NULL AS status, NULL AS final_disposition, a.evidence,
                    a.context_flags, NULL AS value, NULL AS reference_value,
                    NULL AS reviewer, NULL AS reviewed_at, NULL AS review_note,
                    a.created_at, a.algorithm_version
                    """;
        }
        return """
                a.id, a.org_id, o.org_name, a.period, a.var_id, v.var_name,
                a.level, a.category, a.score, a.confidence, a.channel, a.channels,
                a.status, a.final_disposition, a.evidence, a.context_flags,
                a.value, a.reference_value, a.reviewer, a.reviewed_at,
                a.review_note, a.created_at, a.algorithm_version
                """;
    }

    private Dtos.AnomalyRow mapRow(ResultSet rs, boolean watch) throws SQLException {
        return new Dtos.AnomalyRow(
                rs.getLong("id"), watch ? "watch" : "review",
                rs.getString("org_id"), rs.getString("org_name"),
                toLocalDate(rs.getDate("period")), rs.getString("var_id"), rs.getString("var_name"),
                rs.getString("level"), rs.getString("category"), rs.getBigDecimal("score"),
                rs.getBigDecimal("confidence"), rs.getString("channel"), rs.getString("channels"),
                rs.getString("status"), rs.getString("final_disposition"), rs.getString("evidence"),
                rs.getString("context_flags"), rs.getBigDecimal("value"),
                rs.getBigDecimal("reference_value"), rs.getString("reviewer"),
                toLocalDateTime(rs.getTimestamp("reviewed_at")), rs.getString("review_note"),
                toLocalDateTime(rs.getTimestamp("created_at")), rs.getString("algorithm_version")
        );
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
