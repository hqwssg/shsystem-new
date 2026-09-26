package com.example.carbon.emission.model.controller;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
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

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<Map<String, Object>> handleConflict(DataIntegrityViolationException e, HttpServletRequest request) {
        log.warn("Data constraint conflict path={}", request.getRequestURI(), e);
        return response(HttpStatus.CONFLICT.value(), "Request conflicts with existing data", request.getRequestURI());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleException(Exception e, HttpServletRequest request) {
        log.error("Unhandled service exception path={}", request.getRequestURI(), e);
        return response(HttpStatus.INTERNAL_SERVER_ERROR.value(), "Internal server error", request.getRequestURI());
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
