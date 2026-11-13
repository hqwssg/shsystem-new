package com.example.carbon.emission.model.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;

class CarbonAuthorizationFilterTest {
    @Test void CompanySelectionAndAssignmentUseExistingModelEditScope() throws Exception {
        when(client.loadScoped("Bearer test-token","carbon:model:edit")).thenReturn(withPermissions("carbon:model:edit"));
        for (String path : List.of("/api/template/companies","/api/template/create","/api/template/copy/1","/api/template/1/company","/api/template/1/manual-calculate")) {
            MockHttpServletResponse response=new MockHttpServletResponse();
            filter.doFilter(request(path.endsWith("companies")?"GET":"POST",path,true),response,(req,res)->{});
            assertThat(response.getStatus()).isEqualTo(200);
        }
        verify(client,times(5)).loadScoped("Bearer test-token","carbon:model:edit");
        verify(client,never()).load(anyString());
    }
    private final CarbonSecurityProperties properties = new CarbonSecurityProperties();
    private final RuoYiSecurityClient client = mock(RuoYiSecurityClient.class);
    private final CarbonAuthorizationFilter filter = new CarbonAuthorizationFilter(properties, client);

    private CarbonSecurityContext identity() {
        return new CarbonSecurityContext(42L, "employee", "Employee", 12L, "Dept",
                Set.of("employee"), Set.of(), false, false, List.of(12L), List.of());
    }

    @Test void compatibilityModeStillLoadsRealIdentityAndDepartmentScope() throws Exception {
        properties.setEnabled(false);
        CarbonSecurityContext identity = identity();
        when(client.load("Bearer test-token")).thenReturn(identity);
        MockHttpServletRequest request = request("GET", "/api/template/list", true);
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean invoked = new AtomicBoolean();
        filter.doFilter(request, response, (req, res) -> {
            assertThat(req.getAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE)).isSameAs(identity);
            invoked.set(true);
        });
        assertThat(invoked).isTrue();
        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(identity.allData()).isFalse();
        assertThat(identity.deptIds()).containsExactly(12L);
    }

    @Test void compatibilityModeDoesNotAllowAnonymousRequests() throws Exception {
        properties.setEnabled(false);
        assertRejected(request("GET", "/api/security/me", false), 401);
        verifyNoInteractions(client);
    }

    @Test void enabledPermissionModelStillRejectsUnauthorizedOperations() throws Exception {
        when(client.load(anyString())).thenReturn(identity());
        assertRejected(request("GET", "/api/template/list", true), 403);
    }

    @Test void identityEndpointDoesNotRequireOperationPermission() throws Exception {
        when(client.load(anyString())).thenReturn(identity());
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request("GET", "/api/security/me", true), response, (req, res) ->
                assertThat(req.getAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE)).isNotNull());
        assertThat(response.getStatus()).isEqualTo(200);
    }

    @Test void explicitlyExpiredSessionReturns401() throws Exception {
        when(client.load(anyString())).thenThrow(new HttpClientErrorException(HttpStatus.UNAUTHORIZED));
        assertRejected(request("GET", "/api/security/me", true), 401);
    }

    @Test void upstreamForbiddenIsNotReportedAsExpired() throws Exception {
        when(client.load(anyString())).thenThrow(new HttpClientErrorException(HttpStatus.FORBIDDEN));
        assertRejected(request("GET", "/api/security/me", true), 403);
    }

    @Test void networkFailureReturns503InsteadOfExpiringSession() throws Exception {
        when(client.load(anyString())).thenThrow(new ResourceAccessException("connection refused"));
        assertRejected(request("GET", "/api/security/me", true), 503);
    }

    @Test void malformedContextReturns503InsteadOfExpiringSession() throws Exception {
        when(client.load(anyString())).thenThrow(new IllegalStateException("bad context"));
        assertRejected(request("GET", "/api/security/me", true), 503);
    }

    @Test void preflightAndNonApiResourcesRemainOutsideFilter() throws Exception {
        for (MockHttpServletRequest request : List.of(request("OPTIONS", "/api/security/me", false),
                request("GET", "/index.html", false))) {
            AtomicBoolean invoked = new AtomicBoolean();
            filter.doFilter(request, new MockHttpServletResponse(), (req, res) -> invoked.set(true));
            assertThat(invoked).isTrue();
        }
        verifyNoInteractions(client);
    }

    @Test void employeeReadPermissionCannotBeUsedToWriteThroughDirectApiCalls() throws Exception {
        when(client.load(anyString())).thenReturn(withPermissions("carbon:model:view", "carbon:data:edit"));
        when(client.loadScoped(anyString(),eq("carbon:model:edit"))).thenReturn(withPermissions("carbon:model:view", "carbon:data:edit"));
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean read = new AtomicBoolean();
        filter.doFilter(request("GET", "/api/template/list", true), response, (req, res) -> read.set(true));
        assertThat(read).isTrue();
        assertRejected(request("POST", "/api/template/create", true), 403);
        assertRejected(request("POST", "/api/config", true), 403);
    }

    @Test void accountantMayEditModelsWithoutReceivingGlobalParameterPermissions() throws Exception {
        when(client.load(anyString())).thenReturn(withPermissions("carbon:model:view", "carbon:model:edit"));
        when(client.loadScoped(anyString(),eq("carbon:model:edit"))).thenReturn(withPermissions("carbon:model:view", "carbon:model:edit"));
        AtomicBoolean write = new AtomicBoolean();
        filter.doFilter(request("POST", "/api/template/create", true), new MockHttpServletResponse(),
                (req, res) -> write.set(true));
        assertThat(write).isTrue();
        assertRejected(request("POST", "/api/config", true), 403);
    }

    @Test void collectorPermissionDoesNotGrantModelMaintenance() throws Exception {
        when(client.load(anyString())).thenReturn(withPermissions("carbon:params:view", "carbon:params:collection:edit"));
        when(client.loadScoped(anyString(),eq("carbon:model:edit"))).thenReturn(withPermissions("carbon:params:view", "carbon:params:collection:edit"));
        AtomicBoolean operation = new AtomicBoolean();
        filter.doFilter(request("POST", "/api/meter-settings/meters", true), new MockHttpServletResponse(),
                (req, res) -> operation.set(true));
        assertThat(operation).isTrue();
        assertRejected(request("POST", "/api/template/create", true), 403);
    }

    private CarbonSecurityContext withPermissions(String... permissions) {
        return new CarbonSecurityContext(42L, "employee", "Employee", 12L, "Dept", Set.of("employee"),
                Set.of(permissions), false, false, List.of(12L), List.of());
    }

    private MockHttpServletRequest request(String method, String path, boolean token) {
        MockHttpServletRequest request = new MockHttpServletRequest(method, path);
        if (token) request.addHeader("Authorization", "Bearer test-token");
        return request;
    }

    private void assertRejected(MockHttpServletRequest request, int status) throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request, response, (req, res) -> { throw new AssertionError("Rejected request continued"); });
        assertThat(response.getStatus()).isEqualTo(status);
        assertThat(response.getContentAsString()).contains("\"code\":" + status);
    }
}
