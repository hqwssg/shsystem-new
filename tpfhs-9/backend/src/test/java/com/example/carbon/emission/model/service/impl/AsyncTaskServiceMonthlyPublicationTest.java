package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.audit.RuoYiAuditClient;
import com.example.carbon.emission.model.service.EmissionCalculationService;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class AsyncTaskServiceMonthlyPublicationTest {

    @Test
    void schedulerDelegatesToTheOfficialCalculationEntryWithMonthlyPublishingDefaultedOn() {
        EmissionCalculationService calculationService = mock(EmissionCalculationService.class);
        RuoYiAuditClient audit = mock(RuoYiAuditClient.class);
        AsyncTaskService async = new AsyncTaskService();
        ReflectionTestUtils.setField(async, "emissionCalculationService", calculationService);
        ReflectionTestUtils.setField(async, "auditClient", audit);

        async.executeEmissionCalculationAsync(20L, "月度调度模板");

        verify(calculationService).executeEmissionCalculation(20L);
    }
}
