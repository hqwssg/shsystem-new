package com.ruoyi.carbon.analysis.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestParam;
import com.ruoyi.carbon.analysis.service.ManagementDashboardService;
import com.ruoyi.carbon.analysis.service.ScreenDashboardService;
import com.ruoyi.common.core.web.controller.BaseController;
import com.ruoyi.common.core.web.domain.AjaxResult;

@RestController
@RequestMapping("/carbon/screen")
public class ScreenDashboardController extends BaseController
{
    private final ScreenDashboardService screenDashboardService;
    private final ManagementDashboardService managementDashboardService;

    public ScreenDashboardController(ScreenDashboardService screenDashboardService, ManagementDashboardService managementDashboardService)
    {
        this.screenDashboardService = screenDashboardService;
        this.managementDashboardService = managementDashboardService;
    }

    @GetMapping("/dashboard")
    public AjaxResult dashboard(@RequestParam(required = false) String view,
            @RequestParam(required = false) Integer year, @RequestParam(required = false) Long companyId)
    {
        if ("management".equals(view)) return success(managementDashboardService.dashboard(year, companyId));
        if (view != null && !view.isBlank()) throw new com.ruoyi.common.core.exception.ServiceException("未知大屏视图");
        return success(screenDashboardService.dashboard());
    }
}
