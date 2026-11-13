package com.example.carbon.emission.model.security;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

class RuoYiSecurityClientTest {
    @Test void ScopedContextRequiresMatchingServerScopeMarker() {
        server.expect(requestTo(properties.getEndpoint()+"?permission=carbon:model:edit"))
                .andRespond(withSuccess("{\"code\":200,\"data\":{\"userId\":42,\"scopePermission\":\"carbon:model:edit\",\"deptIds\":[12]}}",MediaType.APPLICATION_JSON));
        assertThat(client.loadScoped("Bearer test-token","carbon:model:edit").deptIds()).containsExactly(12L);
        server.verify();
    }

    @Test void OlderUnscopedServerCannotSilentlyWidenCompanyAuthorization() {
        server.expect(requestTo(properties.getEndpoint()+"?permission=carbon:model:edit"))
                .andRespond(withSuccess("{\"code\":200,\"data\":{\"userId\":42,\"allData\":true}}",MediaType.APPLICATION_JSON));
        assertThatThrownBy(()->client.loadScoped("Bearer test-token","carbon:model:edit")).isInstanceOf(IllegalStateException.class);
    }
    private MockRestServiceServer server;
    private RuoYiSecurityClient client;
    private final CarbonSecurityProperties properties = new CarbonSecurityProperties();

    @BeforeEach void setup() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new RuoYiSecurityClient(builder, properties);
    }

    @Test void forwardsTokenAndPreservesVerifiedScope() {
        reply("""
                {"code":200,"data":{"userId":42,"userName":"employee","deptId":12,
                "roles":["employee"],"permissions":["carbon:model:view"],"allData":false,
                "selfOnly":true,"deptIds":[12],"nodeIds":[99]}}
                """);
        CarbonSecurityContext result = client.load("Bearer test-token");
        assertThat(result.userId()).isEqualTo(42L);
        assertThat(result.allData()).isFalse();
        assertThat(result.selfOnly()).isTrue();
        assertThat(result.deptIds()).containsExactly(12L);
        assertThat(result.nodeIds()).containsExactly(99L);
        assertThat(result.hasPermission("carbon:model:edit")).isFalse();
        server.verify();
    }

    @Test void body401IsAnExpiredSession() {
        reply("{\"code\":401,\"msg\":\"expired\"}");
        assertThatThrownBy(() -> client.load("Bearer test-token"))
                .isInstanceOfSatisfying(HttpClientErrorException.class,
                        ex -> assertThat(ex.getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED));
    }

    @Test void body403IsAccessDenied() {
        reply("{\"code\":403}");
        assertThatThrownBy(() -> client.load("Bearer test-token"))
                .isInstanceOfSatisfying(HttpClientErrorException.class,
                        ex -> assertThat(ex.getStatusCode()).isEqualTo(HttpStatus.FORBIDDEN));
    }

    @Test void backendErrorIsNotAnExpiredSession() {
        reply("{\"code\":500,\"msg\":\"database unavailable\"}");
        assertThatThrownBy(() -> client.load("Bearer test-token")).isInstanceOf(IllegalStateException.class);
    }

    @Test void missingIdentityCannotBecomeAnAuthenticatedUser() {
        reply("{\"code\":200,\"data\":{\"allData\":true}}");
        assertThatThrownBy(() -> client.load("Bearer test-token")).isInstanceOf(IllegalStateException.class);
    }

    private void reply(String json) {
        server.expect(requestTo(properties.getEndpoint())).andExpect(header("Authorization", "Bearer test-token"))
                .andRespond(withSuccess(json, MediaType.APPLICATION_JSON));
    }
}
