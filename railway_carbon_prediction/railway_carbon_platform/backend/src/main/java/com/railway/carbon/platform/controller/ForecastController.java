package com.railway.carbon.platform.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.common.ApiResponse;
import com.railway.carbon.platform.dto.Dtos;
import com.railway.carbon.platform.service.ForecastService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/platform")
public class ForecastController {

    private final ForecastService forecastService;

    public ForecastController(ForecastService forecastService) {
        this.forecastService = forecastService;
    }

    @GetMapping("/forecast")
    public ApiResponse<List<Dtos.ForecastRow>> forecast(
            @RequestParam(required = false) String orgId,
            @RequestParam(defaultValue = "BAU") String scenario,
            @RequestParam(required = false) String start,
            @RequestParam(required = false) String end) {
        return ApiResponse.ok(forecastService.forecast(orgId, scenario, start, end));
    }

    @GetMapping("/history")
    public ApiResponse<List<Dtos.HistoryRow>> history(
            @RequestParam(required = false) String orgId,
            @RequestParam(required = false) String start,
            @RequestParam(required = false) String end) {
        return ApiResponse.ok(forecastService.history(orgId, start, end));
    }

    @PostMapping("/forecast/generate")
    public ApiResponse<JsonNode> generate(@Valid @RequestBody Dtos.ForecastGenerateRequest req) {
        return ApiResponse.ok(forecastService.generate(req), "预测任务已执行");
    }

    @GetMapping("/dashboard")
    public ApiResponse<List<Dtos.DashboardSummary>> dashboard() {
        return ApiResponse.ok(forecastService.dashboard());
    }
}
