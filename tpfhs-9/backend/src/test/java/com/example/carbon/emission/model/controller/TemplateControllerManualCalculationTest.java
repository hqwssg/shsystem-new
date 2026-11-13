package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.dto.TemplateDTO;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import com.example.carbon.emission.model.service.EmissionCalculationService;
import com.example.carbon.emission.model.service.TemplateService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class TemplateControllerManualCalculationTest {
    @Mock private TemplateService templateService;
    @Mock private EmissionCalculationService emissionCalculationService;
    @InjectMocks private TemplateController controller;

    @BeforeEach
    void installSecurityContext() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE,
                new CarbonSecurityContext(7L, "tester", "测试员", 3L, "测试部门",
                        Set.of(), Set.of("carbon:model:edit"), true, false, List.of(), List.of()));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
    }

    @AfterEach
    void clearSecurityContext() {
        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void returnsReal422ForManualTaskWithoutValidData() {
        TemplateDTO template = new TemplateDTO();
        template.setTemplateType(2);
        when(templateService.getTemplateById(9L)).thenReturn(template);
        CalculationTemplate task = task(88L, 3, EmissionCalculationService.ERROR_CODE_NO_VALID_DATA);
        when(emissionCalculationService.executeEmissionCalculation(
                9L, LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30), 7L, "tester", true))
                .thenReturn(task);

        ResponseEntity<Map<String, Object>> response = controller.manualCalculate(
                9L, Map.of("startMonth", "2026-09", "endMonth", "2026-09"));

        assertThat(response.getStatusCode().value()).isEqualTo(422);
        assertThat(response.getBody()).containsEntry("taskId", 88L)
                .containsEntry("status", 3)
                .containsEntry("errorCode", EmissionCalculationService.ERROR_CODE_NO_VALID_DATA);
        assertThat(String.valueOf(response.getBody().get("message"))).contains("无有效核算数据");
    }

    @Test
    void keepsSuccessfulManualResponseCompatible() {
        TemplateDTO template = new TemplateDTO();
        template.setTemplateType(2);
        when(templateService.getTemplateById(9L)).thenReturn(template);
        when(emissionCalculationService.executeEmissionCalculation(
                9L, LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30), 7L, "tester", true))
                .thenReturn(task(89L, 2, 0));

        ResponseEntity<Map<String, Object>> response = controller.manualCalculate(
                9L, Map.of("startMonth", "2026-09", "endMonth", "2026-09"));

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody()).containsEntry("taskId", 89L).containsEntry("status", 2);
    }

    @Test
    void returnsReal422AndDetailForDuplicateCollectionPeriod() {
        TemplateDTO template = new TemplateDTO();
        template.setTemplateType(2);
        when(templateService.getTemplateById(9L)).thenReturn(template);
        CalculationTemplate task = task(90L, 3,
                EmissionCalculationService.ERROR_CODE_DUPLICATE_COLLECTION_PERIOD);
        task.setFailureMessage("\u975e\u7d2f\u8ba1\u91c7\u96c6\u70b9\u5b58\u5728\u91cd\u590d\u6709\u6548\u8ba1\u8d39\u5468\u671f\uff1a\u91c7\u96c6\u70b9=90611\uff0c\u5468\u671f=2026-09-30\u81f32026-09-30");
        when(emissionCalculationService.executeEmissionCalculation(
                9L, LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30), 7L, "tester", true))
                .thenReturn(task);

        ResponseEntity<Map<String, Object>> response = controller.manualCalculate(
                9L, Map.of("startMonth", "2026-09", "endMonth", "2026-09"));

        assertThat(response.getStatusCode().value()).isEqualTo(422);
        assertThat(response.getBody())
                .containsEntry("errorCode", EmissionCalculationService.ERROR_CODE_DUPLICATE_COLLECTION_PERIOD);
        assertThat(String.valueOf(response.getBody().get("message")))
                .contains("90611").contains("2026-09-30");
    }

    @Test
    void passesExplicitMonthlyGenerationOptOut() {
        TemplateDTO template = new TemplateDTO();
        template.setTemplateType(2);
        when(templateService.getTemplateById(9L)).thenReturn(template);
        when(emissionCalculationService.executeEmissionCalculation(
                9L, LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30), 7L, "tester", false))
                .thenReturn(task(91L, 2, 0));

        controller.manualCalculate(9L, Map.of(
                "startMonth", "2026-09", "endMonth", "2026-09", "generateMonthlyRecords", false));

        verify(emissionCalculationService).executeEmissionCalculation(
                9L, LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30), 7L, "tester", false);
    }

    private CalculationTemplate task(long id, int status, int errorCode) {
        CalculationTemplate task = new CalculationTemplate();
        task.setId(id);
        task.setStatus(status);
        task.setErrorCode(errorCode);
        task.setCalculationCycleStartDate(LocalDate.of(2026, 9, 1));
        task.setCalculationCycleEndDate(LocalDate.of(2026, 9, 30));
        return task;
    }
}
