package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.entity.CalcNodeSummary;
import com.example.carbon.emission.model.dto.CalcNodeSummaryResponse;
import com.example.carbon.emission.model.service.CalcNodeSummaryService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.service.impl.CalcSummaryExcelExporter;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.data.domain.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * 核算节点汇总 Controller
 * <p>
 * 提供按核算任务、按组织节点 + 周期范围查询节点汇总数据的接口，
 * 供前端核算结果展示、周期性排放对比等场景使用。
 */
@RestController
@RequestMapping("/api/calc-summary")
@CrossOrigin(origins = "*")
public class CalcSummaryController {

    @Autowired
    private CalcNodeSummaryService calcSummaryService;
    @Autowired
    private CalcSummaryExcelExporter excelExporter;

    @GetMapping("/tasks")
    public Page<CalculationTemplate> tasks(
            @RequestParam(required = false) Long templateId,
            @RequestParam(required = false) Integer initiator,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "calculationCycleStartDate") String sortBy,
            @RequestParam(defaultValue = "DESC") String sortDirection) {
        return calcSummaryService.querySuccessfulTasks(templateId, initiator,
                pageable(page, size, sortBy, sortDirection, List.of("id", "calculationCycleStartDate", "calculationStartTime")));
    }

    @GetMapping("/by-template/{taskId}/page")
    public Page<CalcNodeSummaryResponse> byTemplatePage(
            @PathVariable Long taskId,
            @RequestParam(required = false) Long nodeId,
            @RequestParam(required = false) Long sourceNodeId,
            @RequestParam(required = false) String subcategoryCode,
            @RequestParam(required = false) String l1,
            @RequestParam(required = false) String l2,
            @RequestParam(required = false) String l3,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "id") String sortBy,
            @RequestParam(defaultValue = "ASC") String sortDirection) {
        return calcSummaryService.querySuccessfulPage(taskId, nodeId, sourceNodeId, subcategoryCode, l1, l2, l3,
                pageable(page, size, sortBy, sortDirection, List.of("id", "calculationNodeId", "sourceNodeId", "emissionSubcategory")));
    }

    @GetMapping("/export")
    public void export(@RequestParam(required = false) Long templateId,
                       HttpServletResponse response) throws java.io.IOException {
        List<CalculationTemplate> tasks = new java.util.ArrayList<>();
        int taskPageNumber = 0;
        Page<CalculationTemplate> taskPage;
        do {
            taskPage = calcSummaryService.querySuccessfulTasks(templateId, null,
                    PageRequest.of(taskPageNumber++, 1000, Sort.by(Sort.Direction.ASC, "id")));
            tasks.addAll(taskPage.getContent());
        } while (taskPage.hasNext());
        List<CalcNodeSummary> rows = new java.util.ArrayList<>();
        for (CalculationTemplate task : tasks) {
            rows.addAll(calcSummaryService.queryByTemplate(task.getId(), null, null, null, null, null));
            if (rows.size() > 100000) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "导出明细超过100000行，请缩小筛选范围");
        }
        String filename = "碳排放核算结果_全部周期_" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss")) + ".xlsx";
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setHeader("Content-Disposition", "attachment; filename*=UTF-8''" + URLEncoder.encode(filename, StandardCharsets.UTF_8).replace("+", "%20"));
        excelExporter.write(tasks, rows, response.getOutputStream());
    }

    private Pageable pageable(int page, int size, String sortBy, String direction, List<String> allowed) {
        if (page < 0 || size < 1 || size > 100) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "分页参数非法，size必须在1到100之间");
        if (!allowed.contains(sortBy)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "不支持的排序字段: " + sortBy);
        Sort.Direction dir;
        try { dir = Sort.Direction.fromString(direction); }
        catch (IllegalArgumentException ex) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "排序方向必须为ASC或DESC"); }
        return PageRequest.of(page, size, Sort.by(dir, sortBy));
    }
    @Autowired
    private com.example.carbon.emission.model.security.SummaryScopeService summaryScope;

    /**
     * 按核算任务 ID 查询节点汇总
     *
     * @param templateId      核算任务 ID（calculation_template.id）
     * @param nodeId          可选：节点快照 ID
     * @param subcategoryCode 可选：排放小类编码，如 PE_PF
     * @param l1              可选：一级场景
     * @param l2              可选：二级场景
     * @param l3              可选：三级场景
     * @return 匹配的节点汇总列表
     */
    @GetMapping("/by-template/{templateId}")
    public ResponseEntity<List<CalcNodeSummary>> byTemplate(
            @PathVariable Long templateId,
            @RequestParam(value = "nodeId", required = false) Long nodeId,
            @RequestParam(value = "subcategoryCode", required = false) String subcategoryCode,
            @RequestParam(value = "l1", required = false) String l1,
            @RequestParam(value = "l2", required = false) String l2,
            @RequestParam(value = "l3", required = false) String l3) {
        return ResponseEntity.ok(
                summaryScope.filter(calcSummaryService.queryByTemplate(templateId, nodeId, subcategoryCode, l1, l2, l3)));
    }

    /**
     * 按组织节点 + 周期范围查询节点汇总
     *
     * @param sourceNodeId   源节点 ID（必填）
     * @param cycleStartDate 起始日，格式 yyyy-MM-dd（必填）
     * @param cycleEndDate   截止日，格式 yyyy-MM-dd（必填）
     * @return 匹配周期内所有成功核算的汇总列表；参数非法时返回 400 及中文错误说明
     */
    @GetMapping("/by-node-and-cycle")
    public ResponseEntity<?> byNodeAndCycle(
            @RequestParam(value = "sourceNodeId", required = false) Long sourceNodeId,
            @RequestParam(value = "cycleStartDate", required = false) String cycleStartDate,
            @RequestParam(value = "cycleEndDate", required = false) String cycleEndDate) {
        if (sourceNodeId == null) {
            return ResponseEntity.badRequest().body(Map.of("message", "参数 sourceNodeId 缺失或为空"));
        }
        if (cycleStartDate == null || cycleStartDate.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("message", "参数 cycleStartDate 缺失或为空"));
        }
        if (cycleEndDate == null || cycleEndDate.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("message", "参数 cycleEndDate 缺失或为空"));
        }
        LocalDate start;
        LocalDate end;
        try {
            start = LocalDate.parse(cycleStartDate);
        } catch (DateTimeParseException e) {
            return ResponseEntity.badRequest().body(
                    Map.of("message", "cycleStartDate 日期格式错误，应为 yyyy-MM-dd（如 2026-01-01）"));
        }
        try {
            end = LocalDate.parse(cycleEndDate);
        } catch (DateTimeParseException e) {
            return ResponseEntity.badRequest().body(
                    Map.of("message", "cycleEndDate 日期格式错误，应为 yyyy-MM-dd（如 2026-12-31）"));
        }
        return ResponseEntity.ok(summaryScope.filter(calcSummaryService.queryBySourceNodeAndCycle(sourceNodeId, start, end)));
    }
}
