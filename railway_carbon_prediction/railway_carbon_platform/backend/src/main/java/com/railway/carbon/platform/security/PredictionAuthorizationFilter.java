package com.railway.carbon.platform.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.railway.carbon.platform.config.PlatformProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Delegates browser authentication and fine-grained permissions to RuoYi. */
@Component
public class PredictionAuthorizationFilter extends OncePerRequestFilter {
    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final PlatformProperties.Security security;

    public PredictionAuthorizationFilter(RestClient.Builder builder, ObjectMapper objectMapper,
                                         PlatformProperties properties) {
        this.restClient = builder.build();
        this.objectMapper = objectMapper;
        this.security = properties.security();
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String uri = request.getRequestURI();
        return !uri.startsWith("/api/platform/")
                || uri.equals("/api/platform/health")
                || "OPTIONS".equalsIgnoreCase(request.getMethod());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        if (security == null || !security.enabled()) {
            chain.doFilter(request, response);
            return;
        }
        String authorization = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            reject(response, HttpStatus.UNAUTHORIZED, "登录状态缺失，请重新登录");
            return;
        }
        // Read-only pages remain usable for every authenticated account.
        // Fine-grained permissions are reserved for state-changing actions;
        // a missing menu grant must not render every table empty.
        String permission = permissionFor(request);
        try {
            String separator = security.endpoint().contains("?") ? "&" : "?";
            String uri = security.endpoint();
            if (permission != null) {
                uri += separator + "permission="
                        + URLEncoder.encode(permission, StandardCharsets.UTF_8);
            }
            Map<String, Object> body = restClient.get().uri(uri)
                    .header(HttpHeaders.AUTHORIZATION, authorization)
                    .retrieve().body(new ParameterizedTypeReference<>() {});
            int code = body != null && body.get("code") instanceof Number number
                    ? number.intValue() : HttpStatus.SERVICE_UNAVAILABLE.value();
            if (code == HttpStatus.OK.value()) {
                chain.doFilter(request, response);
                return;
            }
            if (code == HttpStatus.UNAUTHORIZED.value()) {
                reject(response, HttpStatus.UNAUTHORIZED, "登录状态已失效，请重新登录");
            } else if (code == HttpStatus.FORBIDDEN.value()) {
                reject(response, HttpStatus.FORBIDDEN, "当前账号没有碳排放趋势预测操作权限");
            } else {
                reject(response, HttpStatus.SERVICE_UNAVAILABLE, "统一权限服务暂不可用");
            }
        } catch (Exception ex) {
            reject(response, HttpStatus.SERVICE_UNAVAILABLE, "统一权限服务暂不可用");
        }
    }

    private String permissionFor(HttpServletRequest request) {
        return permissionFor(request.getMethod(), request.getRequestURI());
    }

    static String permissionFor(String method, String uri) {
        if ("GET".equalsIgnoreCase(method)) return null;
        if (uri.matches(".*/anomalies/[^/]+/review/?$")) return "carbon:prediction:review";
        if (uri.endsWith("/models/train") || ("DELETE".equalsIgnoreCase(method) && uri.contains("/models/"))) {
            return "carbon:prediction:model";
        }
        if (uri.endsWith("/forecast/generate")) return "carbon:prediction:forecast";
        return "carbon:prediction:data:edit";
    }

    private void reject(HttpServletResponse response, HttpStatus status, String message) throws IOException {
        response.setStatus(status.value());
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write(objectMapper.writeValueAsString(Map.of(
                "code", status.value(), "message", message, "data", Map.of())));
    }
}
