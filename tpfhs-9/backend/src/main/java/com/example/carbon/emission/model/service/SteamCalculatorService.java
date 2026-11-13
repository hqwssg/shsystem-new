package com.example.carbon.emission.model.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/** Steam calculations run in the Python service when PYTHON_SERVICE_URL is set. */
@Service
public class SteamCalculatorService {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    @Value("${PYTHON_SERVICE_URL:}") private String serviceUrl;
    @Value("${PYTHON_INTERNAL_TOKEN:}") private String token;
    @Value("${PYTHON_SERVICE_REQUIRED:false}") private boolean required;
    @Value("${PYTHON_PATH:python}") private String python;
    @Value("${STEAM_CALCULATOR_SCRIPT:steam_calculator.py}") private String script;

    public Map<String, Object> calculateSaturationProperties(double temperature) {
        return calculate(List.of("saturation", number(temperature)));
    }

    public Map<String, Object> calculateSuperheatedProperties(double temperature, double pressure) {
        return calculate(List.of("superheated", number(temperature), number(pressure)));
    }

    private static String number(double value) {
        return String.format(Locale.ROOT, "%.6f", value);
    }

    private Map<String, Object> calculate(List<String> args) {
        try {
            String output;
            if (serviceUrl != null && !serviceUrl.isBlank()) {
                if (token == null || token.length() < 32) throw new IllegalStateException("Python 内部服务密钥未配置");
                var payload = Map.of("task", "steam", "args", args, "timeoutSeconds", 30, "maxOutputBytes", 16384);
                var request = HttpRequest.newBuilder(URI.create(serviceUrl.replaceAll("/+$", "") + "/v1/run"))
                        .timeout(Duration.ofSeconds(45)).header("Authorization", "Bearer " + token)
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(payload))).build();
                var response = HTTP.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                if (response.statusCode() != 200) throw new IllegalStateException("Python 服务不可用：HTTP " + response.statusCode());
                JsonNode result = JSON.readTree(response.body());
                if (result.path("timedOut").asBoolean() || result.path("exitCode").asInt(-1) != 0)
                    throw new IllegalStateException("蒸汽计算执行失败或超时");
                output = result.path("stdout").asText();
            } else {
                if (required) throw new IllegalStateException("PYTHON_SERVICE_URL is required");
                List<String> command = new ArrayList<>(List.of(python, script));
                command.addAll(args);
                Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
                try {
                    if (!process.waitFor(30, TimeUnit.SECONDS)) throw new IllegalStateException("蒸汽计算超时");
                    if (process.exitValue() != 0) throw new IllegalStateException("蒸汽计算脚本执行失败");
                    output = new String(process.getInputStream().readNBytes(16384), StandardCharsets.UTF_8);
                } finally {
                    process.descendants().forEach(ProcessHandle::destroyForcibly);
                    if (process.isAlive()) process.destroyForcibly();
                }
            }
            return JSON.readValue(output, new TypeReference<Map<String, Object>>() {});
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            return Map.of("success", false, "error", "蒸汽计算被中断");
        } catch (Exception ex) {
            return Map.of("success", false, "error", "蒸汽计算失败：" + ex.getMessage());
        }
    }
}
