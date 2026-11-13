package com.example.carbon.emission.model.security;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Validates browser requests against the existing RuoYi security context endpoint. */
@Component
public class UncertaintyAuthorizationFilter extends OncePerRequestFilter {
    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String endpoint;
    private final boolean enabled;

    public UncertaintyAuthorizationFilter(RestClient.Builder builder, ObjectMapper objectMapper,
            @Value("${integration.ruoyi-security.endpoint:http://127.0.0.1:8081/internal/security/context}") String endpoint,
            @Value("${integration.ruoyi-security.enabled:true}") boolean enabled) {
        this.restClient = builder.build();
        this.objectMapper = objectMapper;
        this.endpoint = endpoint;
        this.enabled = enabled;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith("/api/uncertainty/")
                || "OPTIONS".equalsIgnoreCase(request.getMethod());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String authorization = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (!enabled) {
            chain.doFilter(request, response);
            return;
        }
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            reject(response, HttpStatus.UNAUTHORIZED, "Missing RuoYi login token");
            return;
        }
        try {
            String uri = endpoint + (endpoint.contains("?") ? "&" : "?")
                    + "permission=carbon:uncertainty:view";
            Map<String, Object> body = restClient.get().uri(uri)
                    .header(HttpHeaders.AUTHORIZATION, authorization)
                    .retrieve().body(new org.springframework.core.ParameterizedTypeReference<>() {});
            int code = body == null || !(body.get("code") instanceof Number n) ? -1 : n.intValue();
            if (code == 401 || code == 403) {
                reject(response, HttpStatus.valueOf(code), code == 401 ? "RuoYi login session is invalid or expired" : "No permission for uncertainty analysis");
                return;
            }
            if (code != 200 || !(body.get("data") instanceof Map<?, ?> data)) {
                reject(response, HttpStatus.SERVICE_UNAVAILABLE, "RuoYi security service is unavailable");
                return;
            }
            UncertaintySecurityContext context = toContext(data);
            if (!context.hasPermission("carbon:uncertainty:view")) {
                reject(response, HttpStatus.FORBIDDEN, "No permission for uncertainty analysis");
                return;
            }
            request.setAttribute(UncertaintySecurityContext.REQUEST_ATTRIBUTE, context);
            chain.doFilter(request, response);
        } catch (Exception ex) {
            reject(response, HttpStatus.SERVICE_UNAVAILABLE, "RuoYi security service is unavailable");
        }
    }

    private UncertaintySecurityContext toContext(Map<?, ?> data) {
        return new UncertaintySecurityContext(
                longValue(data.get("userId")), text(data.get("userName")), longValue(data.get("deptId")),
                strings(data.get("roles")), strings(data.get("permissions")), Boolean.TRUE.equals(data.get("allData")),
                Boolean.TRUE.equals(data.get("selfOnly")), longs(data.get("deptIds")));
    }

    private Long longValue(Object value) { return value instanceof Number n ? n.longValue() : null; }
    private String text(Object value) { return value == null ? null : String.valueOf(value); }
    private Set<String> strings(Object value) {
        if (!(value instanceof Iterable<?> values)) return Collections.emptySet();
        return new java.util.HashSet<>(java.util.stream.StreamSupport.stream(values.spliterator(), false).map(String::valueOf).toList());
    }
    private List<Long> longs(Object value) {
        if (!(value instanceof Iterable<?> values)) return List.of();
        return java.util.stream.StreamSupport.stream(values.spliterator(), false).filter(Number.class::isInstance)
                .map(Number.class::cast).map(Number::longValue).toList();
    }
    private void reject(HttpServletResponse response, HttpStatus status, String message) throws IOException {
        response.setStatus(status.value());
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"code\":" + status.value() + ",\"message\":\"" + message.replace("\"", "'") + "\"}");
    }
}
