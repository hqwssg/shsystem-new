package com.railway.carbon.platform.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.common.ApiResponse;
import com.railway.carbon.platform.common.PageResult;
import com.railway.carbon.platform.dto.Dtos;
import com.railway.carbon.platform.service.DataService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.List;

@RestController
@RequestMapping("/api/platform")
public class DataController {

    private final DataService dataService;

    public DataController(DataService dataService) {
        this.dataService = dataService;
    }

    @GetMapping("/activity")
    public ApiResponse<PageResult<Dtos.ActivityRow>> activity(
            @RequestParam(required = false) String orgId,
            @RequestParam(required = false) String varId,
            @RequestParam(required = false) String start,
            @RequestParam(required = false) String end,
            @RequestParam(required = false) String qualityStatus,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(dataService.activity(orgId, varId, start, end, qualityStatus, page, size));
    }

    @GetMapping("/energy/monthly")
    public ApiResponse<Dtos.MonthlyEnergy> monthlyEnergy(
            @RequestParam String orgId,
            @RequestParam String period) {
        return ApiResponse.ok(dataService.monthlyEnergy(orgId, period));
    }

    @GetMapping("/energy/compare")
    public ApiResponse<Dtos.EnergyCompareResult> compareEnergy(
            @RequestParam String orgId,
            @RequestParam String period,
            @RequestParam String varId,
            @RequestParam BigDecimal value) {
        return ApiResponse.ok(dataService.compareEnergy(orgId, period, varId, value));
    }

    @PostMapping("/activity/ingest")
    public ApiResponse<JsonNode> ingest(@Valid @RequestBody Dtos.IngestRequest req) {
        return ApiResponse.ok(dataService.ingest(req), "数据已接收，异常筛选已启动");
    }

    @GetMapping("/factors")
    public ApiResponse<List<Dtos.FactorRow>> factors(@RequestParam(required = false) String varId) {
        return ApiResponse.ok(dataService.factors(varId));
    }

    @PostMapping("/factors")
    public ApiResponse<Dtos.FactorRow> saveFactor(@Valid @RequestBody Dtos.FactorRequest req) {
        return ApiResponse.ok(dataService.createFactor(req), "因子已保存");
    }

    @GetMapping("/caliber-rules")
    public ApiResponse<List<Dtos.CaliberRuleRow>> caliberRules(
            @RequestParam(required = false) String orgId,
            @RequestParam(required = false) String ruleType) {
        return ApiResponse.ok(dataService.caliberRules(orgId, ruleType));
    }

    @PostMapping("/caliber-rules")
    public ApiResponse<Dtos.CaliberRuleRow> saveCaliberRule(
            @Valid @RequestBody Dtos.CaliberRuleRequest req) {
        return ApiResponse.ok(dataService.saveCaliberRule(req), "口径规则已保存");
    }

    @GetMapping("/policy-factors")
    public ApiResponse<PageResult<Dtos.PolicyFactorRow>> policyFactors(
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String start,
            @RequestParam(required = false) String end,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "30") int size) {
        return ApiResponse.ok(dataService.policyFactors(category, start, end, page, size));
    }

    @PostMapping("/policy-factors")
    public ApiResponse<Integer> savePolicyFactors(
            @Valid @RequestBody Dtos.PolicyFactorBatchRequest req) {
        return ApiResponse.ok(dataService.savePolicyFactors(req.factors()), "政策/外部因子已保存");
    }

    @GetMapping("/calendar-events")
    public ApiResponse<List<Dtos.CalendarEventRow>> calendarEvents() {
        return ApiResponse.ok(dataService.calendarEvents());
    }

    @PostMapping("/calendar-events")
    public ApiResponse<Dtos.CalendarEventRow> saveCalendarEvent(
            @Valid @RequestBody Dtos.CalendarEventRequest req) {
        return ApiResponse.ok(dataService.saveCalendarEvent(req), "日历事件已保存");
    }

    @DeleteMapping("/calendar-events/{id}")
    public ApiResponse<Integer> deleteCalendarEvent(@PathVariable long id) {
        return ApiResponse.ok(dataService.deleteCalendarEvent(id), "日历事件已删除");
    }
}
