package com.railway.carbon.platform.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.railway.carbon.platform.common.ApiResponse;
import com.railway.carbon.platform.dto.Dtos;
import com.railway.carbon.platform.service.ModelService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/platform")
public class ModelController {

    private final ModelService modelService;

    public ModelController(ModelService modelService) {
        this.modelService = modelService;
    }

    @GetMapping("/models")
    public ApiResponse<List<Dtos.ModelRow>> models(
            @RequestParam(required = false) String orgId,
            @RequestParam(defaultValue = "false") boolean championOnly) {
        return ApiResponse.ok(modelService.models(orgId, championOnly));
    }

    @GetMapping("/models/{modelId}")
    public ApiResponse<Dtos.ModelRow> model(@PathVariable String modelId) {
        return ApiResponse.ok(modelService.model(modelId));
    }

    @DeleteMapping("/models/{modelId}")
    public ApiResponse<Map<String, Object>> deleteModel(
            @PathVariable String modelId,
            @RequestParam(defaultValue = "platform") String operator) {
        return ApiResponse.ok(modelService.deleteModel(modelId, operator), "模型已删除");
    }

    @GetMapping("/jobs")
    public ApiResponse<List<Dtos.JobRow>> jobs(@RequestParam(defaultValue = "50") int limit) {
        return ApiResponse.ok(modelService.jobs(limit));
    }

    @GetMapping("/jobs/{jobId}")
    public ApiResponse<JsonNode> job(@PathVariable String jobId) {
        return ApiResponse.ok(modelService.job(jobId));
    }

    @PostMapping("/models/train")
    public ApiResponse<JsonNode> train(@Valid @RequestBody Dtos.TrainRequest req) {
        return ApiResponse.ok(modelService.train(req), "训练任务已提交");
    }
}
