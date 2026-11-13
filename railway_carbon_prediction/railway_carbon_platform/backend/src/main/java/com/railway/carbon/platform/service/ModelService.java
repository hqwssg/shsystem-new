package com.railway.carbon.platform.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.railway.carbon.platform.common.BizException;
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
public class ModelService {

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final PredictionClient predictionClient;

    public ModelService(JdbcTemplate jdbc, ObjectMapper objectMapper,
                        PredictionClient predictionClient) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
        this.predictionClient = predictionClient;
    }

    public List<Dtos.ModelRow> models(String orgId, boolean championOnly) {
        List<Object> args = new ArrayList<>();
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        if (orgId != null && !orgId.isBlank()) {
            where.append(" AND m.org_id = ?");
            args.add(orgId);
        }
        if (championOnly) {
            where.append(" AND m.is_champion = 1");
        }
        String sql = """
                SELECT m.model_id, m.org_id, o.org_name, m.model_type, m.version, m.status,
                       m.is_champion, m.target_var, m.window_size, m.horizon, m.metrics,
                       m.train_start, m.train_end, m.n_samples, m.artifact_path, m.trained_at
                FROM prediction_model m
                LEFT JOIN prediction_org o ON o.org_id = m.org_id
                """ + where + " ORDER BY m.org_id, m.is_champion DESC, m.trained_at DESC";
        return jdbc.query(sql, (rs, i) -> mapModel(rs), args.toArray());
    }

    public Dtos.ModelRow model(String modelId) {
        List<Dtos.ModelRow> rows = jdbc.query("""
                SELECT m.model_id, m.org_id, o.org_name, m.model_type, m.version, m.status,
                       m.is_champion, m.target_var, m.window_size, m.horizon, m.metrics,
                       m.train_start, m.train_end, m.n_samples, m.artifact_path, m.trained_at
                FROM prediction_model m
                LEFT JOIN prediction_org o ON o.org_id = m.org_id
                WHERE m.model_id = ?
                """, (rs, i) -> mapModel(rs), modelId);
        if (rows.isEmpty()) {
            throw new BizException(HttpStatus.NOT_FOUND, "模型不存在");
        }
        return rows.get(0);
    }

    public List<Dtos.JobRow> jobs(int limit) {
        int n = Math.min(Math.max(limit, 1), 200);
        return jdbc.query("""
                SELECT job_id, job_type, status, params, result, error, operator,
                       created_at, started_at, finished_at
                FROM prediction_job
                ORDER BY created_at DESC
                LIMIT ?
                """, (rs, i) -> new Dtos.JobRow(
                rs.getString("job_id"), rs.getString("job_type"), rs.getString("status"),
                parseJson(rs.getString("params")), parseJson(rs.getString("result")),
                rs.getString("error"), rs.getString("operator"),
                toLocalDateTime(rs.getTimestamp("created_at")),
                toLocalDateTime(rs.getTimestamp("started_at")),
                toLocalDateTime(rs.getTimestamp("finished_at"))
        ), n);
    }

    /**
     * 删除已弃用模型。仅允许 status=deprecated，且该模型没有预测结果引用。
     * 模型工件目录不在此接口中删除，避免误删共享文件。
     */
    public Map<String, Object> deleteModel(String modelId, String operator) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT model_id, status, artifact_path, model_type FROM prediction_model WHERE model_id=?",
                modelId);
        if (rows.isEmpty()) {
            throw new BizException(HttpStatus.NOT_FOUND, "模型不存在：" + modelId);
        }
        Map<String, Object> model = rows.get(0);
        if (!"deprecated".equals(model.get("status"))) {
            throw new BizException(HttpStatus.CONFLICT, "只允许删除已弃用（deprecated）模型");
        }
        Long forecasts = jdbc.queryForObject(
                "SELECT COUNT(*) FROM prediction_forecast WHERE model_id=?", Long.class, modelId);
        if (forecasts != null && forecasts > 0) {
            throw new BizException(HttpStatus.CONFLICT,
                    "该模型仍有 " + forecasts + " 条预测结果引用，不能删除；请先归档或清理预测结果");
        }
        int deleted = jdbc.update(
                "DELETE FROM prediction_model WHERE model_id=? AND status='deprecated'", modelId);
        if (deleted == 0) {
            throw new BizException(HttpStatus.CONFLICT, "模型状态已变化，删除失败");
        }
        Map<String, Object> detail = new HashMap<>();
        detail.put("model_id", modelId);
        detail.put("model_type", model.get("model_type"));
        detail.put("artifact_path", model.get("artifact_path"));
        detail.put("forecast_refs", forecasts == null ? 0 : forecasts);
        try {
            jdbc.update("""
                    INSERT INTO prediction_audit_log(action,entity,entity_id,operator,detail)
                    VALUES(?,?,?,?,?)
                    """, "DELETE_MODEL", "prediction_model", modelId,
                    blank(operator) ? "platform" : operator,
                    objectMapper.writeValueAsString(detail));
        } catch (Exception ignored) {
            // 审计失败不回滚模型删除；生产环境可改为同一事务。
        }
        Map<String, Object> result = new HashMap<>();
        result.put("modelId", modelId);
        result.put("deleted", true);
        result.put("artifactPath", model.get("artifact_path"));
        result.put("message", "模型注册记录已删除；工件文件未删除");
        return result;
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }

    public JsonNode train(Dtos.TrainRequest req) {
        Map<String, Object> body = new HashMap<>();
        body.put("org_ids", req.orgIds() == null || req.orgIds().isEmpty()
                ? List.of("JLG", "SNF", "YPF") : req.orgIds());
        body.put("mode", req.mode() == null ? "auto" : req.mode());
        if (req.asOf() != null && !req.asOf().isBlank()) {
            body.put("as_of", req.asOf());
        }
        body.put("force", Boolean.TRUE.equals(req.force()));
        body.put("operator", req.operator() == null ? "platform" : req.operator());
        return predictionClient.train(body);
    }

    public JsonNode job(String jobId) {
        return predictionClient.job(jobId);
    }

    private Dtos.ModelRow mapModel(ResultSet rs) throws SQLException {
        return new Dtos.ModelRow(
                rs.getString("model_id"), rs.getString("org_id"), rs.getString("org_name"),
                rs.getString("model_type"), rs.getString("version"), rs.getString("status"),
                getBoolean(rs, "is_champion"), rs.getString("target_var"),
                (Integer) rs.getObject("window_size"), (Integer) rs.getObject("horizon"),
                parseJson(rs.getString("metrics")), toLocalDate(rs.getDate("train_start")),
                toLocalDate(rs.getDate("train_end")), (Integer) rs.getObject("n_samples"),
                rs.getString("artifact_path"), toLocalDateTime(rs.getTimestamp("trained_at"))
        );
    }

    private Object parseJson(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(text, Object.class);
        } catch (Exception ex) {
            return text;
        }
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

    private static LocalDate toLocalDate(Date date) {
        return date == null ? null : date.toLocalDate();
    }

    private static LocalDateTime toLocalDateTime(java.sql.Timestamp ts) {
        return ts == null ? null : ts.toLocalDateTime();
    }
}
