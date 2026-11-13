package com.ruoyi.carbon.analysis.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.ruoyi.carbon.analysis.service.AnalysisService;
import com.ruoyi.common.core.web.controller.BaseController;
import com.ruoyi.common.core.web.domain.AjaxResult;
import com.ruoyi.common.security.annotation.RequiresPermissions;

@RestController
@RequestMapping("/carbon/analysis")
public class AnalysisController extends BaseController
{
    private final AnalysisService analysisService;

    public AnalysisController(AnalysisService analysisService)
    {
        this.analysisService = analysisService;
    }

    @RequiresPermissions("carbon:analysis:view")
    @GetMapping("/options")
    public AjaxResult options()
    {
        return success(analysisService.options());
    }

    @RequiresPermissions("carbon:analysis:view")
    @GetMapping("/query")
    public AjaxResult query(@RequestParam String grain, @RequestParam String start, @RequestParam String end,
            @RequestParam String orgLevel, @RequestParam(required = false) Long parentNodeId,
            @RequestParam(required = false) String categoryMode, @RequestParam(required = false) String energyCategory,
            @RequestParam(required = false) String subcategory)
    {
        return success(analysisService.query(grain, start, end, orgLevel, parentNodeId, categoryMode, energyCategory, subcategory));
    }

    @RequiresPermissions("carbon:analysis:view")
    @GetMapping("/compare")
    public AjaxResult compare(@RequestParam String compareType, @RequestParam String grain, @RequestParam String period,
            @RequestParam String orgLevel, @RequestParam(required = false) Long parentNodeId,
            @RequestParam(required = false) String orgIds, @RequestParam(required = false) Long orgId,
            @RequestParam(required = false) String categoryMode, @RequestParam(required = false) String energyCategory,
            @RequestParam(required = false) String subcategory)
    {
        return success(analysisService.compare(compareType, grain, period, orgLevel, parentNodeId, orgIds, orgId,
                categoryMode, energyCategory, subcategory));
    }
}
