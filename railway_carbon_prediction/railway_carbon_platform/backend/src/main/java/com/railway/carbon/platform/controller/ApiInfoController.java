package com.railway.carbon.platform.controller;

import com.railway.carbon.platform.common.ApiResponse;
import com.railway.carbon.platform.dto.Dtos;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/platform")
public class ApiInfoController {

    @GetMapping("/api-info")
    public ApiResponse<List<Dtos.ApiInfo>> apiInfo() {
        return ApiResponse.ok(List.of(
                new Dtos.ApiInfo("GET", "/api/platform/forecast?orgId=JLG&scenario=BAU",
                        "获取指定组织未来 12 个月预测结果",
                        "curl \"http://localhost:8080/api/platform/forecast?orgId=JLG&scenario=BAU\""),
                new Dtos.ApiInfo("GET", "/api/platform/history?orgId=JLG&start=2024-01&end=2025-12",
                        "获取历史月度排放结果",
                        "curl \"http://localhost:8080/api/platform/history?orgId=JLG&start=2024-01\""),
                new Dtos.ApiInfo("GET", "/api/platform/energy/monthly?orgId=JLG&period=2025-12",
                        "查询指定分公司指定月份能耗数据（活动数据+排放结果）",
                        "curl \"http://localhost:8080/api/platform/energy/monthly?orgId=JLG&period=2025-12\""),
                new Dtos.ApiInfo("GET", "/api/platform/energy/compare?orgId=JLG&period=2025-12&varId=ELEC_TOTAL&value=148764.116",
                        "比较提交值与库中能耗值：1=相等，0=不相等，2=不存在",
                        "curl \"http://localhost:8080/api/platform/energy/compare?orgId=JLG&period=2025-12&varId=ELEC_TOTAL&value=148764.116\""),
                new Dtos.ApiInfo("GET", "/api/platform/activity?orgId=JLG&page=1&size=20",
                        "分页查询活动数据",
                        "curl \"http://localhost:8080/api/platform/activity?orgId=JLG\""),
                new Dtos.ApiInfo("GET", "/api/platform/anomalies?status=pending",
                        "查询待审核异常",
                        "curl \"http://localhost:8080/api/platform/anomalies?status=pending\""),
                new Dtos.ApiInfo("GET", "/api/platform/models?orgId=JLG",
                        "查询模型版本与指标",
                        "curl \"http://localhost:8080/api/platform/models?orgId=JLG\""),
                new Dtos.ApiInfo("DELETE", "/api/platform/models/{modelId}?operator=platform",
                        "删除已弃用且无预测引用的模型",
                        "curl -X DELETE \"http://localhost:8080/api/platform/models/MODEL_ID?operator=platform\""),
                new Dtos.ApiInfo("GET", "/api/platform/dashboard",
                        "看板汇总：最新排放、未来 12 月预测、待审核异常",
                        "curl \"http://localhost:8080/api/platform/dashboard\"")
        ));
    }

    @GetMapping("/health")
    public ApiResponse<String> health() {
        return ApiResponse.ok("UP");
    }
}
