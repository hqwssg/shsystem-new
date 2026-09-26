package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.security.CarbonSecurityContext;
import com.example.carbon.emission.model.security.CollectionScopeService;
import com.example.carbon.emission.model.service.SystemConfigService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.annotation.PostConstruct;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/** Manual collection records and their review workflow. */
@RestController
@RequestMapping("/api/collection-records")
@CrossOrigin(origins = "*")
public class CollectionRecordController {
    private static final String SUBMITTED = "SUBMITTED";
    private static final String APPROVED = "APPROVED";
    private static final String REJECTED = "REJECTED";
    private static final String AUTO_APPROVE_KEY = "carbon.collection.manual.auto-approve";

    private final JdbcTemplate jdbc;
    private final CollectionScopeService scopes;
    private final SystemConfigService configService;

    public CollectionRecordController(JdbcTemplate jdbc, CollectionScopeService scopes, SystemConfigService configService) {
        this.jdbc = jdbc;
        this.scopes = scopes;
        this.configService = configService;
    }

    @PostConstruct
    void ensureAuditTable() {
        jdbc.execute("CREATE TABLE IF NOT EXISTS emission_collection_record_audit ("
                + "id BIGINT AUTO_INCREMENT PRIMARY KEY,record_id BIGINT NOT NULL,action VARCHAR(30) NOT NULL,"
                + "from_status VARCHAR(20),to_status VARCHAR(20),operator_id BIGINT,operator_name VARCHAR(100),"
                + "comment VARCHAR(500),operated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                + "INDEX idx_collection_audit_record(record_id),INDEX idx_collection_audit_time(operated_at))"
                + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
    }

    @PostMapping("/manual")
    @Transactional
    public ResponseEntity<?> createManual(@Valid @RequestBody ManualCollectionRequest request) {
        CarbonSecurityContext context = CarbonSecurityContext.current();
        scopes.requireCollectionPoint(request.collectionPointType, request.collectionPointId, true);
        Map<String, Object> meter = findMeter(meterTable(request.collectionPointType), request.collectionPointId);
        int method = number(meter.get("meter_reading_method"), 1);
        if (method == 1) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "自动采集节点不允许人工录入");
        if (number(meter.get("status"), 1) != 1) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "采集点未启用，不能录入数据");

        LocalDateTime now = LocalDateTime.now();
        LocalDateTime collectionTime = request.collectionTime == null ? now : request.collectionTime;
        boolean autoApprove = context.hasPermission("carbon:data:review")
                && enabled(configService.getConfig(AUTO_APPROVE_KEY, "false"));
        String workflow = autoApprove ? APPROVED : SUBMITTED;
        String operatorName = context.nickName() != null && !context.nickName().isBlank() ? context.nickName() : context.userName();
        int updated = jdbc.update("insert into emission_collection_record "
                        + "(collection_point_type,collection_point_id,reading_value,collection_time,collection_status,workflow_status,submitter_id,submitted_at,reviewer_id,reviewed_at,review_comment,last_fetch_time,collection_point_name,emission_subcategory,measurement_unit,meter_reading_method,is_cumulative,created_by,updated_by) "
                        + "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                request.collectionPointType, request.collectionPointId, request.readingValue, collectionTime,
                autoApprove ? 1 : 0, workflow, context.userId(), now,
                autoApprove ? context.userId() : null, autoApprove ? now : null,
                autoApprove ? "提交后自动审核通过" : null, autoApprove ? collectionTime : null,
                meter.get("name"), meter.get("emission_subcategory"), meter.get("measurement_unit"), method,
                number(meter.get("is_cumulative"), 0), context.userId(), context.userId());
        if (updated != 1) throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "人工录入保存失败");
        Long recordId = jdbc.queryForObject("select id from emission_collection_record where collection_point_type=? and collection_point_id=? and submitter_id=? order by id desc limit 1", Long.class,
                request.collectionPointType, request.collectionPointId, context.userId());
        addAudit(recordId, autoApprove ? "AUTO_APPROVE" : "SUBMIT", null, workflow, context,
                autoApprove ? "提交后自动审核通过" : "提交待审核");
        if (autoApprove) updateLastCollection(request.collectionPointType, request.collectionPointId, collectionTime, "MANUAL_ENTRY");
        return ResponseEntity.ok(Map.of("status", workflow, "message", autoApprove ? "人工采集数据已自动审核通过" : "人工采集数据已提交，等待审核", "recordId", recordId));
    }

    @GetMapping("/pending")
    public ResponseEntity<List<Map<String, Object>>> pending(@RequestParam Integer collectionPointType, @RequestParam Long collectionPointId) {
        requireReviewPermission();
        scopes.requireCollectionPoint(collectionPointType, collectionPointId, false);
        return ResponseEntity.ok(queryRecords(collectionPointType, collectionPointId, SUBMITTED));
    }

    @PostMapping("/{recordId}/approve")
    @Transactional
    public ResponseEntity<?> approve(@PathVariable Long recordId, @RequestBody(required = false) ReviewRequest request) {
        requireReviewPermission();
        Map<String, Object> record = loadRecord(recordId);
        requireRecordScope(record, false);
        ensureStatus(record, SUBMITTED);
        CarbonSecurityContext context = CarbonSecurityContext.current();
        String comment = defaultText(request == null ? null : request.comment, "审核通过");
        jdbc.update("update emission_collection_record set workflow_status=?,collection_status=1,reviewer_id=?,reviewed_at=?,review_comment=?,updated_by=? where id=? and workflow_status=?", APPROVED, context.userId(), LocalDateTime.now(), comment, context.userId(), recordId, SUBMITTED);
        updateLastCollection(number(record.get("collection_point_type"), 0), longValue(record.get("collection_point_id")), localDateTime(record.get("collection_time")), "MANUAL_ENTRY");
        addAudit(recordId, "APPROVE", SUBMITTED, APPROVED, context, comment);
        return ResponseEntity.ok(Map.of("status", APPROVED, "recordId", recordId));
    }

    @PostMapping("/{recordId}/reject")
    @Transactional
    public ResponseEntity<?> reject(@PathVariable Long recordId, @RequestBody(required = false) ReviewRequest request) {
        requireReviewPermission();
        Map<String, Object> record = loadRecord(recordId);
        requireRecordScope(record, false);
        ensureStatus(record, SUBMITTED);
        CarbonSecurityContext context = CarbonSecurityContext.current();
        String comment = defaultText(request == null ? null : request.comment, "审核驳回");
        jdbc.update("update emission_collection_record set workflow_status=?,collection_status=0,reviewer_id=?,reviewed_at=?,review_comment=?,updated_by=? where id=? and workflow_status=?", REJECTED, context.userId(), LocalDateTime.now(), comment, context.userId(), recordId, SUBMITTED);
        addAudit(recordId, "REJECT", SUBMITTED, REJECTED, context, comment);
        return ResponseEntity.ok(Map.of("status", REJECTED, "recordId", recordId));
    }

    @GetMapping("/latest/{collectionPointType}/{collectionPointId}")
    public ResponseEntity<List<Map<String, Object>>> latest(@PathVariable Integer collectionPointType, @PathVariable Long collectionPointId) {
        scopes.requireCollectionPoint(collectionPointType, collectionPointId, false);
        return ResponseEntity.ok(queryRecords(collectionPointType, collectionPointId, null));
    }

    @GetMapping("/{recordId}/audits")
    public ResponseEntity<List<Map<String, Object>>> audits(@PathVariable Long recordId) {
        Map<String, Object> record = loadRecord(recordId);
        if (SUBMITTED.equals(String.valueOf(record.get("workflow_status")))) requireReviewPermission();
        requireRecordScope(record, false);
        return ResponseEntity.ok(jdbc.queryForList("select id,record_id as recordId,action,from_status as fromStatus,to_status as toStatus,operator_id as operatorId,operator_name as operatorName,comment,operated_at as operatedAt from emission_collection_record_audit where record_id=? order by id asc", recordId));
    }

    private List<Map<String, Object>> queryRecords(Integer type, Long id, String workflow) {
        String sql = "select r.id,r.collection_point_type as collectionPointType,r.collection_point_id as collectionPointId,r.reading_value as readingValue,r.collection_time as collectionTime,r.collection_status as collectionStatus,r.workflow_status as workflowStatus,r.submitter_id as submitterId,coalesce(u.nick_name,u.user_name,cast(r.submitter_id as char)) as submitterName,r.submitted_at as submittedAt,r.reviewer_id as reviewerId,r.reviewed_at as reviewedAt,r.review_comment as reviewComment,r.last_fetch_time as lastFetchTime,r.collection_point_name as collectionPointName,r.emission_subcategory as emissionSubcategory,r.measurement_unit as measurementUnit,r.meter_reading_method as meterReadingMethod,r.is_cumulative as isCumulative,r.created_by as createdBy,r.created_at as createdAt,r.updated_at as updatedAt from emission_collection_record r left join sys_user u on u.user_id=r.submitter_id where r.collection_point_type=? and r.collection_point_id=?";
        if (workflow != null) sql += " and r.workflow_status=?";
        else if (!CarbonSecurityContext.current().hasPermission("carbon:data:review")) sql += " and r.workflow_status <> 'SUBMITTED'";
        sql += " order by r.id desc limit 100";
        return workflow == null ? jdbc.queryForList(sql, type, id) : jdbc.queryForList(sql, type, id, workflow);
    }

    private Map<String, Object> loadRecord(Long id) {
        try { return jdbc.queryForMap("select id,collection_point_type,collection_point_id,collection_time,workflow_status from emission_collection_record where id=?", id); }
        catch (org.springframework.dao.EmptyResultDataAccessException ex) { throw new ResponseStatusException(HttpStatus.NOT_FOUND, "采集记录不存在"); }
    }

    private void requireRecordScope(Map<String, Object> record, boolean write) { scopes.requireCollectionPoint(number(record.get("collection_point_type"), 0), longValue(record.get("collection_point_id")), write); }

    private void ensureStatus(Map<String, Object> record, String expected) {
        if (!expected.equals(String.valueOf(record.get("workflow_status")))) throw new ResponseStatusException(HttpStatus.CONFLICT, "该记录已处理，不能重复审核");
    }

    private void requireReviewPermission() {
        if (!CarbonSecurityContext.current().hasPermission("carbon:data:review")) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "没有采集数据审核权限");
    }

    private void addAudit(Long recordId, String action, String from, String to, CarbonSecurityContext context, String comment) {
        String operator = context.nickName() != null && !context.nickName().isBlank() ? context.nickName() : context.userName();
        jdbc.update("insert into emission_collection_record_audit(record_id,action,from_status,to_status,operator_id,operator_name,comment) values(?,?,?,?,?,?,?)", recordId, action, from, to, context.userId(), operator, comment);
    }

    private void updateLastCollection(Integer type, Long id, LocalDateTime time, String message) {
        String table = meterTable(type);
        jdbc.update("update " + table + " set last_collection_time=?,last_collection_status=1,last_collection_message=? where id=?", time, message, id);
        jdbc.update("update emission_node_config set last_collection_time=?,last_collection_status=1,last_collection_message=? where collection_point_type=? and collection_point_id=?", time, message, type, id);
    }

    private Map<String, Object> findMeter(String table, Long id) {
        try { return jdbc.queryForMap("select id,name,emission_subcategory,measurement_unit,meter_reading_method,is_cumulative,status from " + table + " where id=?", id); }
        catch (org.springframework.dao.EmptyResultDataAccessException ex) { throw new ResponseStatusException(HttpStatus.NOT_FOUND, "采集点不存在"); }
    }

    private String meterTable(Integer type) {
        return switch (type == null ? 0 : type) { case 1 -> "emission_meter_info"; case 2 -> "emission_fossil_fuel_meter_info"; case 3 -> "emission_purchased_heat_meter_info"; default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "无效的采集点类型"); };
    }

    private Integer number(Object value, int fallback) { if (value instanceof Number number) return number.intValue(); try { return value == null ? fallback : Integer.parseInt(String.valueOf(value)); } catch (RuntimeException ex) { return fallback; } }
    private Long longValue(Object value) { try { return value instanceof Number n ? n.longValue() : Long.valueOf(String.valueOf(value)); } catch (RuntimeException ex) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "无效采集点ID"); } }
    private LocalDateTime localDateTime(Object value) { if (value instanceof LocalDateTime time) return time; return value == null ? LocalDateTime.now() : LocalDateTime.parse(String.valueOf(value).replace(' ', 'T')); }
    private String defaultText(String value, String fallback) { return value == null || value.isBlank() ? fallback : value.trim(); }
    private boolean enabled(String value) {
        return value != null && ("true".equalsIgnoreCase(value.trim()) || "1".equals(value.trim()) || "yes".equalsIgnoreCase(value.trim()) || "on".equalsIgnoreCase(value.trim()));
    }

    public static class ManualCollectionRequest {
        @NotNull public Integer collectionPointType;
        @NotNull @Positive public Long collectionPointId;
        @NotNull public BigDecimal readingValue;
        public LocalDateTime collectionTime;
    }
    public static class ReviewRequest { public String comment; }
}
