package com.railway.carbon.platform.controller;

import com.railway.carbon.platform.common.ApiResponse;
import com.railway.carbon.platform.dto.Dtos;
import com.railway.carbon.platform.service.MetaService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/platform/meta")
public class MetaController {

    private final MetaService metaService;

    public MetaController(MetaService metaService) {
        this.metaService = metaService;
    }

    @GetMapping("/orgs")
    public ApiResponse<List<Dtos.Org>> orgs() {
        return ApiResponse.ok(metaService.orgs());
    }

    @GetMapping("/vars")
    public ApiResponse<List<Dtos.Var>> vars() {
        return ApiResponse.ok(metaService.vars());
    }

    @GetMapping("/all")
    public ApiResponse<Map<String, Object>> all() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("orgs", metaService.orgs());
        data.put("vars", metaService.vars());
        return ApiResponse.ok(data);
    }
}
