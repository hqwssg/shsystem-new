package com.example.carbon.emission.model.service.impl;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.net.SocketTimeoutException;
import java.time.YearMonth;
import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class MonthlyPredictionSenderTest {
    @Test
    void resendsIdenticalRequestAfterLostResponse() {
        String base = "https://prediction.test";
        String path = base + "/api/v1/prediction/ingest/monthly";
        var builder = RestClient.builder().baseUrl(base);
        var server = MockRestServiceServer.bindTo(builder).build();
        String body = "{\"idempotency_key\":\"carbon-month-13\",\"records\":[]}";
        for (int attempt = 1; attempt <= 2; attempt++) {
            server.expect(requestTo(path + "/capabilities"))
                    .andRespond(withSuccess("{\"data\":{\"source_snapshot\":1}}", MediaType.APPLICATION_JSON));
            server.expect(requestTo(path)).andExpect(method(HttpMethod.POST)).andExpect(content().string(body))
                    .andRespond(attempt == 1 ? withException(new SocketTimeoutException()) : withSuccess(
                            "{\"code\":0,\"data\":{\"status\":\"pending_review\",\"batch_id\":\"B\"}}",
                            MediaType.APPLICATION_JSON));
        }

        var outbox = mock(MonthlyPredictionOutbox.class);
        var payload = mock(MonthlyPredictionPayload.class);
        var sender = new MonthlyPredictionSender(outbox, payload, builder.build());
        var input = new MonthlyPredictionOutbox.Snapshot(List.of(), List.of(), false);
        var first = new MonthlyPredictionOutbox.Delivery(13, 2, 3, YearMonth.of(2026, 1), 1, input, null, 1);
        var retry = new MonthlyPredictionOutbox.Delivery(13, 2, 3, YearMonth.of(2026, 1), 1, input, body, 2);
        when(outbox.enabled()).thenReturn(true);
        when(outbox.due()).thenReturn(List.of(13L));
        when(outbox.claim(13)).thenReturn(first, retry);
        var request = Map.<String, Object>of("idempotency_key", "carbon-month-13", "records", List.of());
        when(payload.build(first)).thenReturn(request);
        when(outbox.encode(request)).thenReturn(body);
        when(outbox.freeze(first, body)).thenReturn(true);

        sender.drain();
        sender.drain();

        server.verify();
        verify(payload).build(first);
        verifyNoMoreInteractions(payload);
        verify(outbox).finish(first, "RETRY", null, "预测接口连接或响应失败");
        verify(outbox).finish(retry, "PENDING_REVIEW", "B", null);
    }
}
