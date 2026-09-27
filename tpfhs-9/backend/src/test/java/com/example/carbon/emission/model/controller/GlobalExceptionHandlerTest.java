package com.example.carbon.emission.model.controller;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;

class GlobalExceptionHandlerTest {
    @Test
    void permissionDenialRetainsForbiddenStatus() {
        var request = new MockHttpServletRequest("GET", "/api/test");
        var response = new GlobalExceptionHandler().handleStatus(
            new ResponseStatusException(HttpStatus.FORBIDDEN, "Scope denied"), request);
        assertEquals(HttpStatus.FORBIDDEN, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(403, response.getBody().get("status"));
        assertEquals("Forbidden", response.getBody().get("error"));
        assertEquals("Scope denied", response.getBody().get("message"));
        assertEquals("/api/test", response.getBody().get("path"));
    }
}
