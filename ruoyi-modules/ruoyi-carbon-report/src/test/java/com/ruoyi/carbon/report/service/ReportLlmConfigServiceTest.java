package com.ruoyi.carbon.report.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import com.ruoyi.carbon.report.mapper.ReportLlmConfigMapper;
import com.ruoyi.common.core.exception.ServiceException;

class ReportLlmConfigServiceTest
{
    @Test void encryptedDefaultsSurviveServiceRestartAndBlankKeyPreservesThem()
    {
        Map<String, String> stored = new HashMap<>();
        ReportLlmConfigMapper mapper = mock(ReportLlmConfigMapper.class);
        when(mapper.selectValue(anyString())).thenAnswer(i -> stored.get(i.getArgument(0)));
        when(mapper.updateValue(anyString(), anyString(), anyString())).thenAnswer(i -> {
            stored.put(i.getArgument(0), i.getArgument(1)); return 1;
        });
        MockEnvironment env = new MockEnvironment().withProperty("CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY", "test-stable-secret");
        ReportLlmConfigService service = new ReportLlmConfigService(mapper, env);
        service.saveDefault(Map.of("baseUrl", "https://example.com/v1/", "model", "model-a", "apiKey", "test-api-secret"), "admin");
        String encrypted = stored.get("carbon.report.llm.default.apiKeyEncrypted");
        assertTrue(encrypted.startsWith("v1:"));
        assertFalse(encrypted.contains("test-api-secret"));
        ReportLlmConfigService restarted = new ReportLlmConfigService(mapper, env);
        assertEquals("test-api-secret", restarted.resolve(Map.of()).getApiKey());
        assertEquals("https://example.com/v1", restarted.resolve(Map.of()).getBaseUrl());
        restarted.saveDefault(Map.of("baseUrl", "https://example.com/v1", "model", "model-b", "apiKey", ""), "admin");
        assertEquals(encrypted, stored.get("carbon.report.llm.default.apiKeyEncrypted"));
        assertEquals("test-api-secret", restarted.publicSettings(false).get("apiKey"));
        assertEquals(false, restarted.publicSettings(false).get("isAdmin"));
        assertEquals("request-key", restarted.resolve(Map.of("apiKey", "request-key")).getApiKey());
        assertEquals(encrypted, stored.get("carbon.report.llm.default.apiKeyEncrypted"));
        assertThrows(ServiceException.class, () -> new ReportLlmConfigService(mapper,
                new MockEnvironment().withProperty("CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY", "different-key")).resolve(Map.of()));
    }

    @Test void rejectsMissingEncryptionKeyAndInvalidUrlWithoutLeakingSecret()
    {
        ReportLlmConfigMapper mapper = mock(ReportLlmConfigMapper.class);
        ReportLlmConfigService service = new ReportLlmConfigService(mapper, new MockEnvironment());
        ServiceException ex = assertThrows(ServiceException.class, () -> service.saveDefault(
                Map.of("baseUrl", "https://example.com", "model", "model-a", "apiKey", "test-api-secret"), "admin"));
        assertFalse(ex.getMessage().contains("test-api-secret"));
        assertThrows(ServiceException.class, () -> service.resolve(Map.of("baseUrl", "https://user:password@example.com")));
        assertThrows(ServiceException.class, () -> service.resolve(Map.of("baseUrl", "file:///tmp/model")));
    }
}
