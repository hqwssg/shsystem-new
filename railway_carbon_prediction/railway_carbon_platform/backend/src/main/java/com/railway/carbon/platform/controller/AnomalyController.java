package com.railway.carbon.platform.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.common.ApiResponse;
import com.railway.carbon.platform.common.PageResult;
import com.railway.carbon.platform.dto.Dtos;
import com.railway.carbon.platform.service.AnomalyService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/platform/anomalies")
public class AnomalyController {

    private final AnomalyService anomalyService;

    public AnomalyController(AnomalyService anomalyService) {
        this.anomalyService = anomalyService;
    }

    @GetMapping
    public ApiResponse<PageResult<Dtos.AnomalyRow>> list(
            @RequestParam(defaultValue = "review") String scope,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String orgId,
            @RequestParam(required = false) String level,
            @RequestParam(required = false) String start,
            @RequestParam(required = false) String end,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ApiResponse.ok(anomalyService.list(scope, status, orgId, level, start, end, page, size));
    }

    @GetMapping("/{id}")
    public ApiResponse<Dtos.AnomalyRow> detail(@PathVariable long id,
                                               @RequestParam(defaultValue = "review") String scope) {
        return ApiResponse.ok(anomalyService.detail(id, scope));
    }

    @PostMapping("/{id}/review")
    public ApiResponse<JsonNode> review(@PathVariable long id,
                                        @Valid @RequestBody Dtos.ReviewRequest req) {
        return ApiResponse.ok(anomalyService.review(id, req), "审核已提交");
    }
}
