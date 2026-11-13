package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.security.CollectionScopeService;
import com.example.carbon.emission.model.service.EmissionDataFreshnessService;
import com.example.carbon.emission.model.service.SystemConfigService;
import jakarta.validation.Validation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class ManualReadingNonnegativeValidationTest {
    @Mock JdbcTemplate jdbc;
    @Mock CollectionScopeService scopes;
    @Mock SystemConfigService configService;
    @Mock EmissionDataFreshnessService freshnessService;

    @ParameterizedTest
    @ValueSource(ints = {1, 2, 3})
    void manualApiRejectsNegativeReadingBeforeAnyDatabaseWrite(int pointType) throws Exception {
        var controller = new CollectionRecordController(jdbc, scopes, configService, freshnessService);
        var mvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        mvc.perform(post("/api/collection-records/manual")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"collectionPointType":%d,"collectionPointId":9,"readingValue":-1}
                                """.formatted(pointType)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("人工采集读数不能为负数"));
        verifyNoInteractions(jdbc, scopes, configService, freshnessService);
    }

    @Test
    void zeroIsAValidManualReading() {
        var request = new CollectionRecordController.ManualCollectionRequest();
        request.collectionPointType = 1;
        request.collectionPointId = 9L;
        request.readingValue = BigDecimal.ZERO;
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            assertThat(factory.getValidator().validate(request)).isEmpty();
        }
    }
}
