package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.dto.DqiScoreSubmitRequest;
import com.example.carbon.emission.model.dto.DqiSuggestionDto;
import com.example.carbon.emission.model.dto.ScopeCompletenessResult;
import com.example.carbon.emission.model.dto.SimulationConfig;
import com.example.carbon.emission.model.dto.UncertaintyAuditDto;
import com.example.carbon.emission.model.dto.UncertaintyDimensionSetDto;
import com.example.carbon.emission.model.dto.UncertaintyRulesetCreateRequest;
import com.example.carbon.emission.model.dto.UncertaintyRulesetDto;
import com.example.carbon.emission.model.dto.UncertaintyReportDto;
import com.example.carbon.emission.model.dto.UncertaintyRunDetailDto;
import com.example.carbon.emission.model.dto.UncertaintySourceMetaUpdateRequest;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyRun;
import com.example.carbon.emission.model.entity.UncertaintyScopeBaseline;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.service.DqiScoringService;
import com.example.carbon.emission.model.service.ScopeCompletenessService;
import com.example.carbon.emission.model.service.UncertaintyReportService;
import com.example.carbon.emission.model.service.UncertaintyRulesetService;
import com.example.carbon.emission.model.service.UncertaintySimulationService;
import com.example.carbon.emission.model.service.CalculationTaskQueryService;
import com.example.carbon.emission.model.security.UncertaintySecurityContext;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * 不确定性分析（DQI+MCS）模块 Controller
 * <p>
 * 面向核算任务中心，calcTemplateId 为核算任务ID。覆盖规则库版本管理、
 * 排放源元信息导入与补录、DQI 自动评分与人工复核、Scope 级完整性
 * 基准与评估、蒙特卡洛模拟运行与结果查询。
 * <p>
 * 异常处理沿用全局 {@link GlobalExceptionHandler}，本类不做 try/catch。
 */
@RestController
@RequestMapping("/api/uncertainty")
@CrossOrigin(origins = "*")
public class UncertaintyController {

    @Autowired
    private CalculationTaskQueryService calculationTaskQueryService;

    @GetMapping("/calculation-tasks")
    public ResponseEntity<List<com.example.carbon.emission.model.dto.CalculationTaskOption>> listCalculationTasks(
            @RequestParam(value = "templateName", required = false) String templateName,
            @RequestParam(value = "companyName", required = false) String companyName,
            @RequestParam(value = "year", required = false) Integer year) {
        Object value = org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        UncertaintySecurityContext context = value instanceof org.springframework.web.context.request.ServletRequestAttributes attrs
                && attrs.getRequest().getAttribute(UncertaintySecurityContext.REQUEST_ATTRIBUTE) instanceof UncertaintySecurityContext c ? c : null;
        return ResponseEntity.ok(calculationTaskQueryService.findSuccessful(templateName, companyName, year, context));
    }

    /**
     * DQI 规则库服务
     */
    @Autowired
    private UncertaintyRulesetService rulesetService;

    /**
     * DQI 自动评分引擎服务
     */
    @Autowired
    private DqiScoringService dqiScoringService;

    /**
     * Scope 级完整性分量服务
     */
    @Autowired
    private ScopeCompletenessService scopeCompletenessService;

    /**
     * 不确定性模拟运行服务
     */
    @Autowired
    private UncertaintySimulationService simulationService;

    /**
     * 不确定性报告生成服务（O5）
     */
    @Autowired
    private UncertaintyReportService reportService;

    // ============================== 规则库 ==============================

    /**
     * 确保内置默认规则库存在（幂等）
     *
     * @return 200 + {id: 规则库ID}
     */
    @PostMapping("/rulesets/ensure-default")
    public ResponseEntity<Map<String, Object>> ensureDefaultRuleset() {
        Long id = rulesetService.ensureDefaultRuleset();
        return ResponseEntity.ok(Map.of("id", id));
    }

    /**
     * 新建规则库版本（含规范 5.9 治理规则阻断校验）
     *
     * @param request 新建规则库请求（含维度规则列表）
     * @return 200 + {id: 新建规则库ID}
     */
    @PostMapping("/rulesets")
    public ResponseEntity<Map<String, Object>> createRuleset(@RequestBody UncertaintyRulesetCreateRequest request) {
        Long id = rulesetService.createRuleset(request);
        return ResponseEntity.ok(Map.of("id", id));
    }

    /**
     * 查询全部规则库版本列表（不含维度规则明细）
     *
     * @return 规则库版本列表
     */
    @GetMapping("/rulesets")
    public ResponseEntity<List<UncertaintyRulesetDto>> listRulesets() {
        return ResponseEntity.ok(rulesetService.listRulesets());
    }

    /**
     * 按版本号查询规则库详情（含维度规则列表）
     *
     * @param version 规则库版本号
     * @return 规则库详情
     */
    @GetMapping("/rulesets/{version}")
    public ResponseEntity<UncertaintyRulesetDto> getRuleset(@PathVariable String version) {
        return ResponseEntity.ok(rulesetService.getRuleset(version));
    }

    /**
     * 查询指定参数类型的启用维度集与归一化上下界
     * <p>
     * 返回 enabled=1 维度清单（dimCode/dimName/weight/enabled）及
     * ∑Qmin_w=Σw、∑Qmax_w=5Σw（仅 weight&gt;0 维度参与求和）。
     *
     * @param version   规则库版本号
     * @param paramType 参数类型：AD / EF
     * @return 启用维度集
     */
    @GetMapping("/rulesets/{version}/dimension-set")
    public ResponseEntity<UncertaintyDimensionSetDto> getDimensionSet(
            @PathVariable String version,
            @RequestParam String paramType) {
        return ResponseEntity.ok(rulesetService.getDimensionSet(version, paramType));
    }

    // ============================== 排放源与评分 ==============================

    /**
     * 从核算结果快照导入排放源元信息（I1，幂等）
     *
     * @param calcTemplateId 核算任务ID
     * @param calcYear       可选：核算年度，缺省由服务层从核算任务周期推定
     * @return 200 + {imported: 导入/更新条数}
     */
    @PostMapping("/{calcTemplateId}/sources/import")
    public ResponseEntity<Map<String, Object>> importSources(
            @PathVariable Long calcTemplateId,
            @RequestParam(value = "calcYear", required = false) Integer calcYear) {
        int count = dqiScoringService.importSources(calcTemplateId, calcYear);
        return ResponseEntity.ok(Map.of("imported", count));
    }

    /**
     * 查询核算任务下全部排放源元信息列表
     *
     * @param calcTemplateId 核算任务ID
     * @return 排放源元信息列表
     */
    @GetMapping("/{calcTemplateId}/sources")
    public ResponseEntity<List<UncertaintySourceMeta>> listSources(@PathVariable Long calcTemplateId) {
        return ResponseEntity.ok(dqiScoringService.listSources(calcTemplateId));
    }

    /**
     * 人工补录/修改排放源元信息（仅更新非 null 字段）
     *
     * @param metaId  排放源元信息ID
     * @param request 元信息修改请求
     * @return 200 + {success, message}
     */
    @PutMapping("/sources/{metaId}")
    public ResponseEntity<Map<String, Object>> updateSourceMeta(
            @PathVariable Long metaId,
            @RequestBody UncertaintySourceMetaUpdateRequest request) {
        dqiScoringService.updateSourceMeta(metaId, request);
        return ResponseEntity.ok(Map.of("success", true, "message", "更新成功"));
    }

    /**
     * M2a 五步算法生成/刷新建议分
     *
     * @param calcTemplateId  核算任务ID
     * @param rulesetVersion 可选：规则库版本号，缺省取最新版本
     * @param calcYear       可选：核算年度，缺省由服务层推定
     * @return 每排放源的维度评分结果与警告列表
     */
    @GetMapping("/{calcTemplateId}/dqi/suggestions")
    public ResponseEntity<List<DqiSuggestionDto>> getSuggestions(
            @PathVariable Long calcTemplateId,
            @RequestParam(value = "rulesetVersion", required = false) String rulesetVersion,
            @RequestParam(value = "calcYear", required = false) Integer calcYear) {
        return ResponseEntity.ok(dqiScoringService.generateSuggestions(calcTemplateId, rulesetVersion, calcYear));
    }

    /**
     * 查询排放源的 DQI 评分记录
     *
     * @param metaId    排放源元信息ID
     * @param paramType 可选：AD / EF，缺省返回全部参数类型
     * @return 评分记录列表
     */
    @GetMapping("/sources/{metaId}/dqi")
    public ResponseEntity<List<UncertaintyScore>> getScores(
            @PathVariable Long metaId,
            @RequestParam(value = "paramType", required = false) String paramType) {
        return ResponseEntity.ok(dqiScoringService.getScores(metaId, paramType));
    }

    /**
     * I2 人工复核提交（单排放源单参数类型一批维度评分）
     *
     * @param metaId    排放源元信息ID
     * @param paramType 参数类型：AD / EF
     * @param reviewer  可选：复核人
     * @param request   提交请求
     * @return 200 + {success, message}
     */
    @PostMapping("/sources/{metaId}/dqi")
    public ResponseEntity<Map<String, Object>> submitScores(
            @PathVariable Long metaId,
            @RequestParam String paramType,
            @RequestParam(value = "reviewer", required = false) String reviewer,
            @RequestBody DqiScoreSubmitRequest request) {
        dqiScoringService.submitScores(metaId, paramType, request, reviewer);
        return ResponseEntity.ok(Map.of("success", true, "message", "提交成功"));
    }

    /**
     * 审计链查询（O6，按时间倒序）
     *
     * @param metaId 排放源元信息ID
     * @return 审计记录列表
     */
    @GetMapping("/sources/{metaId}/dqi/audit")
    public ResponseEntity<List<UncertaintyAuditDto>> getAudit(@PathVariable Long metaId) {
        return ResponseEntity.ok(dqiScoringService.getAudit(metaId));
    }

    // ============================== Scope 基准与完整性 ==============================

    /**
     * 新增或更新某 Scope 的 I6 独立基准（按 calcTemplateId+scope upsert）
     *
     * @param calcTemplateId 核算任务ID
     * @param request        基准请求体 {scope, benchmarkQty, benchmarkUnit, benchmarkSource}
     * @return 200 + {success, message}
     */
    @PostMapping("/{calcTemplateId}/scope-baseline")
    public ResponseEntity<Map<String, Object>> saveBaseline(
            @PathVariable Long calcTemplateId,
            @RequestBody ScopeBaselineRequest request) {
        scopeCompletenessService.saveBaseline(calcTemplateId, request.getScope(),
                request.getBenchmarkQty(), request.getBenchmarkUnit(), request.getBenchmarkSource());
        return ResponseEntity.ok(Map.of("success", true, "message", "保存成功"));
    }

    /**
     * 查询核算任务下全部 Scope 独立基准列表
     *
     * @param calcTemplateId 核算任务ID
     * @return 基准列表
     */
    @GetMapping("/{calcTemplateId}/scope-baseline")
    public ResponseEntity<List<UncertaintyScopeBaseline>> listBaselines(@PathVariable Long calcTemplateId) {
        return ResponseEntity.ok(scopeCompletenessService.listBaselines(calcTemplateId));
    }

    /**
     * 每 Scope 完整性评估（O7，不落库，实时计算）
     *
     * @param calcTemplateId  核算任务ID
     * @param rulesetVersion 可选：规则库版本号，缺省取最新版本
     * @return 每个 Scope 一条评估结果
     */
    @GetMapping("/{calcTemplateId}/scope-completeness")
    public ResponseEntity<List<ScopeCompletenessResult>> getScopeCompleteness(
            @PathVariable Long calcTemplateId,
            @RequestParam(value = "rulesetVersion", required = false) String rulesetVersion) {
        UncertaintyRuleset ruleset = (rulesetVersion != null && !rulesetVersion.isBlank())
                ? rulesetService.getRulesetEntity(rulesetVersion)
                : rulesetService.getLatestRuleset();
        return ResponseEntity.ok(scopeCompletenessService.compute(calcTemplateId, ruleset));
    }

    // ============================== 模拟与结果 ==============================

    /**
     * 触发一次蒙特卡洛模拟运行（M3→M5）
     * <p>
     * 大样本量（nIterations ≥ 100000）采用异步执行：本接口以 RUNNING 状态落库
     * 运行记录后立即返回 runId，后台线程完成抽样与统计；调用方据此轮询
     * {@code GET /api/uncertainty/runs/{runId}} 获取状态（RUNNING → SUCCESS/FAILED）
     * 与结果。小样本量同步执行至完成后返回。
     *
     * @param calcTemplateId 核算任务ID
     * @param config        模拟配置（可全空，空值由服务层填默认值）
     * @return 200 + {runId: 运行记录ID}
     */
    @PostMapping("/{calcTemplateId}/simulation/run")
    public ResponseEntity<Map<String, Object>> runSimulation(
            @PathVariable Long calcTemplateId,
            @RequestBody(required = false) SimulationConfig config) {
        Long runId = simulationService.run(calcTemplateId, config);
        return ResponseEntity.ok(Map.of("runId", runId));
    }

    /**
     * 查询核算任务下全部模拟运行列表（按ID倒序，最新在前）
     *
     * @param calcTemplateId 核算任务ID
     * @return 模拟运行列表
     */
    @GetMapping("/{calcTemplateId}/runs")
    public ResponseEntity<List<UncertaintyRun>> listRuns(@PathVariable Long calcTemplateId) {
        return ResponseEntity.ok(simulationService.listRuns(calcTemplateId));
    }

    /**
     * 查询单次模拟运行的完整结果详情
     * <p>
     * O3/O4（运行记录字段）+ O7（Scope 级完整性评估）+ O1（参数级结果）。
     *
     * @param runId 模拟运行ID
     * @return 运行结果详情
     */
    @GetMapping("/runs/{runId}")
    public ResponseEntity<UncertaintyRunDetailDto> getRunDetail(@PathVariable Long runId) {
        return ResponseEntity.ok(simulationService.getRunDetail(runId));
    }

    // ============================== 报告生成（O5） ==============================

    /**
     * 生成单次模拟运行的不确定性报告（O5，全量章节 JSON）
     * <p>
     * 章节：任务信息与配置快照、点估计与上抬、MCS 统计量与置信区间、
     * 无偏性验证与不确定性等级（O4）、Scope 级完整性披露（O7）、
     * 参数级明细（O1）、警告集合。仅 SUCCESS 状态的运行可生成。
     *
     * @param runId 模拟运行ID
     * @return 不确定性报告
     */
    @GetMapping("/runs/{runId}/report")
    public ResponseEntity<UncertaintyReportDto> getRunReport(@PathVariable Long runId) {
        return ResponseEntity.ok(reportService.getReport(runId));
    }

    /**
     * 导出单次模拟运行的不确定性报告 PDF（O5，附件下载）
     *
     * @param runId 模拟运行ID
     * @return PDF 文件流（Content-Disposition: attachment）
     */
    @GetMapping("/runs/{runId}/report/pdf")
    public ResponseEntity<byte[]> getRunReportPdf(@PathVariable Long runId) {
        byte[] pdf = reportService.getReportPdf(runId);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_PDF);
        headers.setContentDisposition(ContentDisposition.attachment()
                .filename("uncertainty-report-" + runId + ".pdf", StandardCharsets.UTF_8)
                .build());
        return new ResponseEntity<>(pdf, headers, HttpStatus.OK);
    }

    /**
     * Scope 独立基准保存请求体（I6）
     */
    public static class ScopeBaselineRequest {
        /**
         * Scope类别
         */
        private String scope;
        /**
         * 独立自上而下基准量（必须为正）
         */
        private BigDecimal benchmarkQty;
        /**
         * 基准量单位
         */
        private String benchmarkUnit;
        /**
         * 基准来源
         */
        private String benchmarkSource;

        public String getScope() { return scope; }
        public void setScope(String v) { this.scope = v; }
        public BigDecimal getBenchmarkQty() { return benchmarkQty; }
        public void setBenchmarkQty(BigDecimal v) { this.benchmarkQty = v; }
        public String getBenchmarkUnit() { return benchmarkUnit; }
        public void setBenchmarkUnit(String v) { this.benchmarkUnit = v; }
        public String getBenchmarkSource() { return benchmarkSource; }
        public void setBenchmarkSource(String v) { this.benchmarkSource = v; }
    }
}
