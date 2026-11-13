package com.example.carbon.emission.model.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import java.time.Duration;

@Service
public class MonthlyPredictionSender {
    private static final Logger log = LoggerFactory.getLogger(MonthlyPredictionSender.class);
    private static final String PATH = "/api/v1/prediction/ingest/monthly";
    private final MonthlyPredictionOutbox outbox;
    private final MonthlyPredictionPayload payload;
    private final RestClient client;

    @Autowired
    public MonthlyPredictionSender(MonthlyPredictionOutbox outbox, MonthlyPredictionPayload payload,
            @Value("${carbon.statistics.prediction-send.base-url:}") String url,
            @Value("${carbon.statistics.prediction-send.api-key:}") String key) {
        this(outbox, payload, predictionClient(url, key));
    }

    MonthlyPredictionSender(MonthlyPredictionOutbox outbox, MonthlyPredictionPayload payload, RestClient client) {
        this.outbox = outbox;
        this.payload = payload;
        this.client = client;
    }

    private static RestClient predictionClient(String url, String key) {
        if (url.isBlank() || key.isBlank()) return null;
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(5));
        factory.setReadTimeout(Duration.ofSeconds(60));
        return RestClient.builder().requestFactory(factory).baseUrl(url).defaultHeader("X-API-Key", key).build();
    }

    public void drain() {
        if (client == null || !outbox.enabled()) return;
        try {
            JsonNode capabilities = client.get().uri(PATH + "/capabilities").retrieve().body(JsonNode.class);
            if (capabilities == null || capabilities.path("data").path("source_snapshot").asInt() != 1) return;
            for (long id : outbox.due()) {
                if (!outbox.enabled()) return;
                MonthlyPredictionOutbox.Delivery job = outbox.claim(id);
                if (job != null) send(job);
            }
        } catch (RestClientException error) {
            log.warn("预测月度入库能力暂不可用，保留待发送记录");
        }
    }

    private void send(MonthlyPredictionOutbox.Delivery job) {
        try {
            String body = job.request();
            if (body == null) {
                body = outbox.encode(payload.build(job));
                if (!outbox.freeze(job, body)) return;
            }
            JsonNode reply = client.post().uri(PATH).contentType(MediaType.APPLICATION_JSON)
                    .body(body).retrieve().body(JsonNode.class);
            if (reply == null || reply.path("code").asInt(-1) != 0) {
                outbox.finish(job, "RETRY", null, "预测接口未确认接收");
                return;
            }
            JsonNode result = reply.path("data");
            String status = switch (result.path("status").asText()) {
                case "completed" -> "COMPLETED";
                case "pending_review" -> "PENDING_REVIEW";
                case "skipped_existing" -> "SKIPPED_EXISTING";
                case "unchanged" -> "UNCHANGED";
                case "superseded" -> "SUPERSEDED";
                default -> "RETRY";
            };
            outbox.finish(job, status, result.path("batch_id").asText(null),
                    "RETRY".equals(status) ? "预测回执状态未知" : null);
        } catch (RestClientResponseException error) {
            int code = error.getStatusCode().value();
            var headers = error.getResponseHeaders();
            String reason = headers == null ? "" : headers.getFirst("X-Prediction-Ingest-Error");
            String failure = switch (reason == null ? "" : reason) {
                case "factor_version" -> "预测排放因子版本冲突";
                case "factor_ambiguous" -> "预测排放因子存在多个匹配";
                case "factor_missing" -> "预测排放因子缺失";
                default -> "预测接口 HTTP " + code;
            };
            outbox.finish(job, code >= 500 || code == 429 ? "RETRY" : "BLOCKED", null, failure);
        } catch (RestClientException error) {
            outbox.finish(job, "RETRY", null, "预测接口连接或响应失败");
        } catch (IllegalArgumentException | IllegalStateException error) {
            String reason = error.getMessage();
            outbox.finish(job, "BLOCKED", null, reason == null ? "预测发送配置错误"
                    : reason.substring(0, Math.min(480, reason.length())));
        }
    }
}
