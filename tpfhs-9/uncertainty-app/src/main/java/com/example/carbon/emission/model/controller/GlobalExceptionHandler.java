package com.example.carbon.emission.model.controller;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.InvalidDataAccessApiUsageException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, Object>> handleStatus(ResponseStatusException e, HttpServletRequest request) {
        return response(e.getStatusCode().value(), e.getReason(), request.getRequestURI());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException e, HttpServletRequest request) {
        String message = e.getBindingResult().getFieldErrors().stream().findFirst()
                .map(error -> error.getDefaultMessage()).orElse("Request parameters are invalid");
        return response(HttpStatus.BAD_REQUEST.value(), message, request.getRequestURI());
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, IllegalArgumentException.class})
    public ResponseEntity<Map<String, Object>> handleBadRequest(Exception e, HttpServletRequest request) {
        return response(HttpStatus.BAD_REQUEST.value(), e.getMessage(), request.getRequestURI());
    }

    /**
     * 业务规则约束异常（服务层主动抛出，message 面向业务方可读）：
     * - IllegalStateException："存在未完成的DQI评分，禁止运行模拟"
     * - IllegalStateException："规则库不存在"
     * - 等等
     * 业务方需要看到这条信息来引导下一步操作，返回 422 Unprocessable Entity。
     */
    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<Map<String, Object>> handleBusiness(IllegalStateException e, HttpServletRequest request) {
        log.warn("Business rule rejected path={}, msg={}", request.getRequestURI(), e.getMessage());
        return response(HttpStatus.UNPROCESSABLE_ENTITY.value(), e.getMessage(), request.getRequestURI());
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<Map<String, Object>> handleConflict(DataIntegrityViolationException e, HttpServletRequest request) {
        log.warn("Data constraint conflict path={}", request.getRequestURI(), e);
        return response(HttpStatus.CONFLICT.value(), "Request conflicts with existing data", request.getRequestURI());
    }

    /**
     * 数据库访问异常（列不存在、表不存在等）：
     * 这种情况说明后端与当前数据库 schema 不匹配，通常是没执行 update 脚本，
     * 需要把 SQL 层的关键信息透出以便排查。
     */
    @ExceptionHandler({BadSqlGrammarException.class, InvalidDataAccessApiUsageException.class})
    public ResponseEntity<Map<String, Object>> handleDb(Exception e, HttpServletRequest request) {
        log.error("Schema mismatch path={}", request.getRequestURI(), e);
        // 沿 cause 链取最内层非空 message（MySQLSyntaxErrorException 在链条末端）
        String rootMsg = e.getMessage();
        Throwable cur = e.getCause();
        while (cur != null) {
            if (cur.getMessage() != null && !cur.getMessage().isBlank()) {
                rootMsg = cur.getMessage();
            }
            cur = cur.getCause();
        }
        String user = "数据库 schema 与后端代码不匹配：" + rootMsg;
        return response(HttpStatus.INTERNAL_SERVER_ERROR.value(), user, request.getRequestURI());
    }

    /**
     * 兜底运行时异常：透传业务 message（运行时只有 uncertainty-app 这一层，
     * 不会泄露基础设施堆栈），完整堆栈记录在后端日志里。
     */
    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<Map<String, Object>> handleRuntime(RuntimeException e, HttpServletRequest request) {
        log.error("Unhandled runtime exception path={}", request.getRequestURI(), e);
        return response(HttpStatus.INTERNAL_SERVER_ERROR.value(),
                e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage(), request.getRequestURI());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleException(Exception e, HttpServletRequest request) {
        log.error("Unhandled exception path={}", request.getRequestURI(), e);
        return response(HttpStatus.INTERNAL_SERVER_ERROR.value(),
                e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage(), request.getRequestURI());
    }

    private ResponseEntity<Map<String, Object>> response(int status, String message, String path) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("timestamp", Instant.now().toString());
        body.put("status", status);
        body.put("error", HttpStatus.valueOf(status).getReasonPhrase());
        body.put("message", message == null || message.isBlank() ? "Request failed" : message);
        body.put("path", path);
        return ResponseEntity.status(status).body(body);
    }
}
