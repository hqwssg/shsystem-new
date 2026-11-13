package com.railway.carbon.platform.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.railway.carbon.platform.common.BizException;
import com.railway.carbon.platform.config.PlatformProperties;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.time.Duration;
import java.util.Map;

@Service
public class PredictionClient {

    private final RestClient client;
    private final ObjectMapper objectMapper;

    public PredictionClient(PlatformProperties properties, ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        PlatformProperties.Prediction cfg = properties.prediction();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        int timeout = Math.max(cfg.timeoutSeconds(), 10);
        factory.setConnectTimeout(Duration.ofSeconds(5));
        factory.setReadTimeout(Duration.ofSeconds(timeout));
        this.client = RestClient.builder()
                .baseUrl(cfg.baseUrl())
                .defaultHeader("X-API-Key", cfg.apiKey())
                .requestFactory(factory)
                .build();
    }

    public JsonNode ingest(Map<String, Object> body) {
        return post("/api/v1/prediction/ingest/monthly", body);
    }

    public JsonNode review(long anomalyId, Map<String, Object> body) {
        return post("/api/v1/prediction/anomalies/" + anomalyId + "/review", body);
    }

    public JsonNode train(Map<String, Object> body) {
        return post("/api/v1/prediction/train", body);
    }

    public JsonNode generateForecast(Map<String, Object> body) {
        return post("/api/v1/prediction/forecast", body);
    }

    public JsonNode job(String jobId) {
        return get("/api/v1/prediction/jobs/" + jobId);
    }

    private JsonNode post(String path, Map<String, Object> body) {
        try {
            JsonNode root = client.post().uri(path)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(JsonNode.class);
            return unwrap(root);
        } catch (RestClientResponseException ex) {
            throw mapError(ex);
        } catch (Exception ex) {
            throw new BizException(HttpStatus.BAD_GATEWAY,
                    "预测算法服务不可用，请先启动 Python FastAPI 服务：" + ex.getMessage());
        }
    }

    private JsonNode get(String path) {
        try {
            JsonNode root = client.get().uri(path).retrieve().body(JsonNode.class);
            return unwrap(root);
        } catch (RestClientResponseException ex) {
            throw mapError(ex);
        } catch (Exception ex) {
            throw new BizException(HttpStatus.BAD_GATEWAY,
                    "预测算法服务不可用，请先启动 Python FastAPI 服务：" + ex.getMessage());
        }
    }

    private JsonNode unwrap(JsonNode root) {
        if (root == null) {
            throw new BizException(HttpStatus.BAD_GATEWAY, "预测算法服务返回为空");
        }
        int code = root.path("code").asInt(0);
        if (code != 0) {
            throw new BizException(HttpStatus.BAD_GATEWAY,
                    root.path("message").asText("预测算法服务返回错误"));
        }
        return root.path("data");
    }

    private BizException mapError(RestClientResponseException ex) {
        HttpStatus status = HttpStatus.resolve(ex.getStatusCode().value());
        if (status == null) {
            status = HttpStatus.BAD_GATEWAY;
        }
        String message = ex.getResponseBodyAsString();
        try {
            JsonNode node = objectMapper.readTree(message);
            if (node.has("detail")) {
                message = node.get("detail").asText();
            } else if (node.has("message")) {
                message = node.get("message").asText();
            }
        } catch (Exception ignored) {
            // keep raw body
        }
        return new BizException(status, message);
    }
}
