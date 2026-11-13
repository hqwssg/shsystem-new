package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.dto.CreateTemplateRequest;
import com.example.carbon.emission.model.dto.TemplateDTO;
import com.example.carbon.emission.model.dto.TemplateValidationResultVO;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import com.example.carbon.emission.model.service.EmissionCalculationService;
import com.example.carbon.emission.model.service.TemplateService;
import com.example.carbon.emission.model.service.TemplateValidationService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.time.YearMonth;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;

@RestController
@RequestMapping("/api/template")
@CrossOrigin(origins = "*", allowCredentials = "false")
public class TemplateController {
    
    @Autowired
    private TemplateService templateService;

    @Autowired
    private TemplateValidationService templateValidationService;

    @Autowired
    private EmissionCalculationService emissionCalculationService;

    @Autowired
    private com.example.carbon.emission.model.service.impl.CompanyOwnershipService companies;

    @Autowired
    private com.example.carbon.emission.model.service.impl.StatisticsBaselineTemplateService statisticsBaselineTemplates;

    @GetMapping("/companies")
    public Object companies() { return companies.options(); }

    @PutMapping("/{id}/company")
    public Object assignCompany(@PathVariable Long id, @RequestBody Map<String,Object> request) {
        return templateService.assignCompany(id, requiredLong(request, "companyDeptId"), Boolean.TRUE.equals(request.get("confirmLegacyTasks")));
    }

    @PutMapping("/{id}/statistics-baseline")
    public Object setStatisticsBaseline(@PathVariable Long id) {
        return statisticsBaselineTemplates.set(id);
    }

    @GetMapping("/statistics-baseline")
    public Object statisticsBaselines() {
        return statisticsBaselineTemplates.accessible();
    }

    @GetMapping("/list")
    public ResponseEntity<List<TemplateDTO>> getAllTemplates() {
        return ResponseEntity.ok(templateService.getAllTemplates());
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<TemplateDTO> getTemplateById(@PathVariable Long id) {
        return ResponseEntity.ok(templateService.getTemplateById(id));
    }
    
    @PostMapping("/create")
    public ResponseEntity<TemplateDTO> createTemplate(@Valid @RequestBody CreateTemplateRequest request) {
        return ResponseEntity.ok(templateService.createTemplate(request));
    }
    
    @PutMapping("/{id}")
    public ResponseEntity<TemplateDTO> updateTemplate(@PathVariable Long id, @RequestBody Map<String, Object> request) {
        String name = (String) request.get("name");
        Long updatedBy = requiredLong(request, "updatedBy");
        return ResponseEntity.ok(templateService.updateTemplate(id, name, updatedBy));
    }
    
    @Autowired
    private ObjectMapper objectMapper;
    
    @PutMapping("/{id}/properties")
    public ResponseEntity<TemplateDTO> updateTemplateProperties(@PathVariable Long id, @RequestBody Map<String, Object> request) {
        String description = (String) request.get("description");
        Boolean enabled = (Boolean) request.get("enabled");

        // 模版类型：1-节点模版；2-核算模版
        Integer templateType = null;
        Object templateTypeObj = request.get("templateType");
        if (templateTypeObj instanceof Number) {
            templateType = ((Number) templateTypeObj).intValue();
        }

        String taskConfig = null;
        Object taskConfigObj = request.get("taskConfig");
        if (taskConfigObj != null) {
            if (taskConfigObj instanceof String) {
                taskConfig = (String) taskConfigObj;
            } else {
                try {
                    taskConfig = objectMapper.writeValueAsString(taskConfigObj);
                } catch (JsonProcessingException e) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "任务配置必须是合法JSON对象", e);
                }
            }
        }

        Long updatedBy = requiredLong(request, "updatedBy");

        Long factorTemplateId = null;
        Object factorTemplateIdObj = request.get("factorTemplateId");
        if (factorTemplateIdObj instanceof Number) {
            factorTemplateId = ((Number) factorTemplateIdObj).longValue();
        }

        return ResponseEntity.ok(templateService.updateTemplate(id, description, enabled, templateType, taskConfig, factorTemplateId, updatedBy));
    }
    
    @PostMapping("/copy/{sourceId}")
    public ResponseEntity<TemplateDTO> copyTemplate(@PathVariable Long sourceId, @RequestBody Map<String, Object> request) {
        String newName = (String) request.get("newName");
        Long createdBy = ((Number) request.get("createdBy")).longValue();
        Long companyDeptId = request.get("companyDeptId") instanceof Number value ? value.longValue() : null;
        return ResponseEntity.ok(templateService.copyTemplate(sourceId, newName, createdBy, companyDeptId));
    }
    
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteTemplate(@PathVariable Long id) {
        templateService.deleteTemplate(id);
        return ResponseEntity.ok().build();
    }

    /**
     * 校验核算模版（仅核算模版有效）
     * <p>
     * 执行完整性校验：因子模版设置、采集点存在且启用、能耗小类覆盖、
     * 单独因子与因子模版一致性、空核算节点。结果保存到 emission_template
     * 的 check_result / check_time / check_message 字段并返回。
     *
     * @param id 核算模版ID
     * @return 校验结果（含富文本告警信息与结构化明细）
     */
    @PostMapping("/{id}/validate")
    public ResponseEntity<TemplateValidationResultVO> validateTemplate(@PathVariable Long id) {
        return ResponseEntity.ok(templateValidationService.validateTemplate(id));
    }

    /**
     * 查看核算模版最近一次校验结果（不重新校验）
     *
     * @param id 核算模版ID
     * @return 校验结果（含富文本告警信息）；未校验过时 checkResult=0
     */
    @GetMapping("/{id}/validation-result")
    public ResponseEntity<TemplateValidationResultVO> getValidationResult(@PathVariable Long id) {
        return ResponseEntity.ok(templateValidationService.getValidationResult(id));
    }

    /**
     * 按用户指定的完整月份执行一次手动核算。
     * 请求只接受 yyyy-MM，服务端负责生成当月第一天和最后一天，避免前端传入非法日界限。
     */
    @PostMapping("/{id}/manual-calculate")
    public ResponseEntity<Map<String, Object>> manualCalculate(@PathVariable Long id,
                                                                @RequestBody Map<String, Object> request) {
        CarbonSecurityContext context = CarbonSecurityContext.current();
        if (!context.hasPermission("carbon:model:edit")) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "没有手动核算权限");
        }
        // Manual execution is a write operation even though it also reads the template.
        // Company-sensitive requests carry the existing model-edit data scope.
        TemplateDTO template = templateService.getTemplateById(id);
        if (template == null || !Integer.valueOf(2).equals(template.getTemplateType())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "仅核算模版支持手动核算");
        }

        String startMonth = text(request.get("startMonth"));
        String endMonth = text(request.get("endMonth"));
        if (startMonth == null || endMonth == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请填写核算起止月份");
        }

        YearMonth start;
        YearMonth end;
        try {
            DateTimeFormatter formatter = DateTimeFormatter.ofPattern("uuuu-MM");
            start = YearMonth.parse(startMonth, formatter);
            end = YearMonth.parse(endMonth, formatter);
        } catch (DateTimeParseException ex) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "月份格式错误，应为 yyyy-MM", ex);
        }
        if (start.isAfter(end)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "起始月份不能晚于截止月份");
        }
        boolean generateMonthlyRecords = !(request.get("generateMonthlyRecords") instanceof Boolean value)
                || value;

        CalculationTemplate task = emissionCalculationService.executeEmissionCalculation(
                id, start.atDay(1), end.atEndOfMonth(), context.userId(), context.userName(),
                generateMonthlyRecords);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "该模板周期已存在核算任务或模板不存在");
        }
        Integer status = task.getStatus();
        String message;
        if (task.isReusedExistingResult()) {
            message = task.getCompanyDeptId() == null
                    ? "已有历史核算结果尚未确认公司归属，请在设置归属公司时核对并确认历史任务"
                    : "该周期已有核算结果";
        } else if (Integer.valueOf(2).equals(status)) {
            message = "手动核算已完成，已生成新结果";
            if ("FAILED".equals(task.getMonthlyRecordStatus())) {
                message += "；" + task.getMonthlyRecordMessage();
            }
        } else if (Integer.valueOf(1).equals(status) || Integer.valueOf(0).equals(status)) {
            message = "该周期核算正在执行";
        } else if (Integer.valueOf(3).equals(status)) {
            message = "该周期核算失败，请查看任务日志后重试";
        } else {
            message = "核算任务已提交";
        }
        boolean duplicatePeriod = Integer.valueOf(EmissionCalculationService.ERROR_CODE_DUPLICATE_COLLECTION_PERIOD)
                .equals(task.getErrorCode());
        String failureMessage = task.getFailureMessage() != null && !task.getFailureMessage().isBlank()
                ? task.getFailureMessage() : message;
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("taskId", task.getId());
        body.put("status", status);
        body.put("errorCode", task.getErrorCode() == null ? 0 : task.getErrorCode());
        body.put("startDate", task.getCalculationCycleStartDate());
        body.put("endDate", task.getCalculationCycleEndDate());
        body.put("message", Integer.valueOf(EmissionCalculationService.ERROR_CODE_NO_VALID_DATA)
                .equals(task.getErrorCode())
                ? "无有效核算数据：所选周期内没有已审核且状态正常的采集记录"
                : failureMessage);
        body.put("monthlyRecordStatus", task.getMonthlyRecordStatus());
        body.put("monthlyRecordMessage", task.getMonthlyRecordMessage());
        if (Integer.valueOf(EmissionCalculationService.ERROR_CODE_NO_VALID_DATA).equals(task.getErrorCode())
                || duplicatePeriod) {
            return ResponseEntity.unprocessableEntity().body(body);
        }
        return ResponseEntity.ok(body);
    }

    private String text(Object value) {
        if (value == null) return null;
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    private Long requiredLong(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof Number)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + "不能为空且必须为数字");
        }
        return ((Number) value).longValue();
    }
}
