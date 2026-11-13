package com.railway.carbon.platform.security;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class PredictionAuthorizationFilterTest {

    @Test
    void readOnlyRequestsDoNotRequirePredictionMenuPermission() {
        assertNull(PredictionAuthorizationFilter.permissionFor("GET", "/api/platform/activity"));
        assertNull(PredictionAuthorizationFilter.permissionFor("GET", "/api/platform/history"));
        assertNull(PredictionAuthorizationFilter.permissionFor("GET", "/api/platform/dashboard"));
    }

    @Test
    void stateChangingRequestsKeepFineGrainedPermissions() {
        assertEquals("carbon:prediction:data:edit",
                PredictionAuthorizationFilter.permissionFor("POST", "/api/platform/activity/ingest"));
        assertEquals("carbon:prediction:model",
                PredictionAuthorizationFilter.permissionFor("POST", "/api/platform/models/train"));
        assertEquals("carbon:prediction:forecast",
                PredictionAuthorizationFilter.permissionFor("POST", "/api/platform/forecast/generate"));
        assertEquals("carbon:prediction:review",
                PredictionAuthorizationFilter.permissionFor("POST", "/api/platform/anomalies/7/review"));
    }
}
