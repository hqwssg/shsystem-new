package com.example.carbon.emission.model.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 页面“自动抄表接口测试”使用的安全探测器。
 *
 * <p>与正式采集适配器采用相同的响应契约校验，但不保存采集记录。返回值只包含
 * 脱敏后的业务字段，绝不回显原始响应、密码、Token 或 Authorization。</p>
 */
@Component
public class HttpReadingProbe {

    private final ObjectMapper objectMapper;

    public HttpReadingProbe(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> probe(Map<String, Object> config) {
        String interfaceType = text(config, "interfaceType", "");
        if (!"HTTP_API".equals(interfaceType)) {
            return failure("目前仅支持 HTTP_API 的真实连通性测试");
        }
        String apiUrl = text(config, "apiUrl", "").trim();
        if (apiUrl.isEmpty()) {
            return failure("接口地址不能为空");
        }

        int timeout = integer(config.get("timeout"), 10);
        if (timeout < 1 || timeout > 60) {
            return failure("超时时间必须在1至60秒之间");
        }

        try {
            HttpRequest.Builder request = HttpRequest.newBuilder()
                    .uri(URI.create(apiUrl))
                    .timeout(Duration.ofSeconds(timeout))
                    .GET();
            applyAuthentication(request, config);
            HttpResponse<String> response = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(timeout))
                    .build()
                    .send(request.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return failure("HTTP接口返回非2xx状态码：" + response.statusCode());
            }

            JsonNode root = objectMapper.readTree(response.body());
            BigDecimal value = decimal(required(root, text(config, "valuePath", text(config, "dataPath", "data.readingValue")), "读数"));
            if (value.signum() < 0) {
                return failure("读数不能为负数");
            }
            String device = required(root, text(config, "devicePath", "data.deviceAddress"), "设备地址").asText();
            String expectedDevice = text(config, "deviceAddress", "").trim();
            if (!expectedDevice.isEmpty() && !expectedDevice.equals(device)) {
                return failure("响应设备地址与配置不一致");
            }
            String collectedAt = required(root, text(config, "timePath", "data.collectedAt"), "采集时间").asText();
            OffsetDateTime.parse(collectedAt);
            String readingId = required(root, text(config, "recordIdPath", "data.readingId"), "外部记录ID").asText();
            String unit = required(root, text(config, "unitPath", "data.measurementUnit"), "计量单位").asText();
            String quality = required(root, text(config, "qualityPath", "data.quality"), "质量状态").asText();
            if (readingId.isBlank() || unit.isBlank() || quality.isBlank()) {
                return failure("响应中的记录ID、单位和质量状态不能为空");
            }

            Map<String, Object> data = new LinkedHashMap<>();
            data.put("readingId", readingId);
            data.put("deviceAddress", device);
            data.put("readingValue", value.toPlainString());
            data.put("measurementUnit", unit);
            data.put("collectedAt", collectedAt);
            data.put("quality", quality);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("success", true);
            result.put("message", "HTTP接口及读数响应结构校验通过");
            result.put("data", data);
            return result;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return failure("接口调用被中断");
        } catch (Exception e) {
            return failure("接口响应校验失败：" + safeMessage(e));
        }
    }

    private void applyAuthentication(HttpRequest.Builder request, Map<String, Object> config) {
        String authType = text(config, "authType", "NONE");
        if ("BASIC".equals(authType)) {
            String raw = text(config, "username", "") + ":" + text(config, "password", "");
            request.header("Authorization", "Basic " + Base64.getEncoder().encodeToString(raw.getBytes(StandardCharsets.UTF_8)));
        } else if ("TOKEN".equals(authType) || "BEARER".equals(authType)) {
            request.header("Authorization", "Bearer " + text(config, "token", ""));
        }
    }

    private JsonNode required(JsonNode root, String path, String label) {
        JsonNode current = root;
        for (String part : path.split("\\.")) {
            current = current == null ? null : current.get(part);
        }
        if (current == null || current.isNull() || (current.isTextual() && current.asText().isBlank())) {
            throw new IllegalArgumentException(label + "路径无有效值：" + path);
        }
        return current;
    }

    private BigDecimal decimal(JsonNode node) {
        try {
            return new BigDecimal(node.asText());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("读数不是合法数值");
        }
    }

    private Map<String, Object> failure(String message) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("success", false);
        result.put("message", message);
        return result;
    }

    private String text(Map<String, Object> config, String key, String fallback) {
        Object value = config.get(key);
        return value == null ? fallback : String.valueOf(value);
    }

    private int integer(Object value, int fallback) {
        try {
            return value == null ? fallback : Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private String safeMessage(Exception e) {
        if (e instanceof IllegalArgumentException && e.getMessage() != null) {
            return e.getMessage();
        }
        return e.getClass().getSimpleName();
    }
}
