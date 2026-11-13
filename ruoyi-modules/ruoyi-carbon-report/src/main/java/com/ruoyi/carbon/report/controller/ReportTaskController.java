package com.ruoyi.carbon.report.controller;

import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import com.alibaba.fastjson2.JSON;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.service.ReportSubjectService;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.CreateReportRequest;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.generation.ReportImageSlots;
import com.ruoyi.carbon.report.service.IReportDeptProfileService;
import com.ruoyi.carbon.report.service.IReportGenerationService;
import com.ruoyi.carbon.report.service.IReportSourceService;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.carbon.report.service.ReportPreflight;
import com.ruoyi.carbon.report.service.ReportLlmConfigService;
import com.ruoyi.carbon.report.generation.LlmRuntimeConfig;
import com.ruoyi.carbon.report.source.ReportExcelType;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.core.web.controller.BaseController;
import com.ruoyi.common.core.web.domain.AjaxResult;
import com.ruoyi.common.log.annotation.Log;
import com.ruoyi.common.log.enums.BusinessType;
import com.ruoyi.common.security.annotation.RequiresPermissions;
import com.ruoyi.common.security.utils.SecurityUtils;

@RestController
@RequestMapping("/carbon/report")
public class ReportTaskController extends BaseController
{
    @Autowired
    private IReportTaskService reportTaskService;

    @Autowired
    private ReportSubjectService reportSubjects;

    @Autowired
    private IReportSourceService reportSourceService;

    @Autowired
    private IReportGenerationService reportGenerationService;

    @Autowired
    private IReportDeptProfileService reportDeptProfileService;

    @Autowired
    private ReportPreflight reportPreflight;

    @Autowired
    private ReportLlmConfigService reportLlmConfigService;

    @Autowired
    private com.ruoyi.carbon.report.source.ReportComparisonService reportComparisons;

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/tasks/{id}/comparisons")
    public AjaxResult comparisons(@PathVariable Long id) {
        return success(reportComparisons.candidates(reportTaskService.get(id, reportSubjects.reportDept(id))));
    }

    @RequiresPermissions("carbon:report:list")
    @GetMapping("/tasks")
    public AjaxResult list(ReportTask query)
    {
        if (query.getDeptId() != null) query.setDeptId(currentDept(query.getDeptId()));
        List<ReportTask> list = reportTaskService.list(query);
        return success(list);
    }

    @RequiresPermissions("carbon:report:add")
    @Log(title = "碳排放报告", businessType = BusinessType.INSERT)
    @PostMapping("/tasks")
    @org.springframework.transaction.annotation.Transactional(rollbackFor = Exception.class)
    public AjaxResult create(@RequestBody CreateReportRequest request)
    {
        Long deptId = reportSubjects.requireCompany(request.getDeptId());
        ReportTask task = reportTaskService.create(request, deptId, SecurityUtils.getUsername());
        if (!task.isCreationReused() && request.getCalculationTemplateId() != null && !Boolean.TRUE.equals(request.getDeferPrefill()))
        {
            reportSourceService.commit(task.getId(), deptId, request.getCalculationTemplateId());
            task = reportTaskService.get(task.getId(), deptId);
        }
        return success(task);
    }

    @RequiresPermissions("carbon:report:remove")
    @Log(title = "碳排放报告", businessType = BusinessType.DELETE)
    @DeleteMapping("/tasks/{id}")
    public AjaxResult remove(@PathVariable Long id)
    {
        reportTaskService.remove(id, reportSubjects.reportDept(id), SecurityUtils.getUsername());
        return success();
    }

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/tasks/{id}")
    public AjaxResult get(@PathVariable Long id)
    {
        return success(reportTaskService.get(id, reportSubjects.reportDept(id)));
    }

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/tasks/{id}/draft")
    public AjaxResult draft(@PathVariable Long id)
    {
        return success(reportTaskService.getDraft(id, reportSubjects.reportDept(id)));
    }

    @RequiresPermissions("carbon:report:edit")
    @PutMapping("/tasks/{id}/sections/{section}")
    public AjaxResult saveSection(@PathVariable Long id, @PathVariable String section, @RequestBody Map<String, Object> body)
    {
        Integer version = body.get("version") == null ? null : Integer.valueOf(String.valueOf(body.get("version")));
        Object data = body.get("data");
        String payload = data == null ? "{}" : JSON.toJSONString(data);
        return success(reportTaskService.saveSection(id, reportSubjects.reportDept(id), section, version, payload, SecurityUtils.getUsername()));
    }

    @RequiresPermissions("carbon:report:edit")
    @GetMapping("/tasks/{id}/excel-templates/{type}")
    public ResponseEntity<byte[]> excelTemplate(@PathVariable Long id, @PathVariable String type)
    {
        reportTaskService.get(id, reportSubjects.reportDept(id));
        ReportExcelType excelType = ReportExcelType.from(type);
        byte[] data = reportTaskService.excelTemplate(type);
        String filename = excelType.label + ".xlsx";
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + filename + "\"; filename*=UTF-8''"
                        + java.net.URLEncoder.encode(filename, java.nio.charset.StandardCharsets.UTF_8).replace("+", "%20"))
                .contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .contentLength(data.length)
                .body(data);
    }

    @RequiresPermissions("carbon:report:edit")
    @Log(title = "碳排放报告", businessType = BusinessType.IMPORT)
    @PostMapping(value = "/tasks/{id}/excel-import/{type}", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public AjaxResult importExcel(@PathVariable Long id, @PathVariable String type,
            @RequestParam("mode") String mode, @RequestParam("version") Integer version,
            @RequestParam("file") MultipartFile file)
    {
        if (file == null || file.isEmpty())
        {
            throw new ServiceException("请选择 Excel 文件", HttpStatus.BAD_REQUEST);
        }
        try
        {
            return success(reportTaskService.importExcel(id, reportSubjects.reportDept(id), type, mode, version,
                    file.getOriginalFilename(), file.getInputStream(), SecurityUtils.getUsername()));
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("导入失败: " + ex.getMessage());
        }
    }

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/source/calculations")
    public AjaxResult calculations(@RequestParam(required = false) Date periodStart, @RequestParam(required = false) Date periodEnd,
            @RequestParam(required = false) Long deptId, @RequestParam(required = false) String periodMode)
    {
        Long company = reportSubjects.requireCompany(deptId);
        var candidates = reportSourceService.listCalculations(company, periodStart, periodEnd);
        return success("CALCULATION".equals(periodMode)
                ? candidates.stream().filter(row -> company.equals(row.getCompanyDeptId())).toList() : candidates);
    }

    public AjaxResult calculations(Date periodStart, Date periodEnd, Long deptId) {
        return calculations(periodStart, periodEnd, deptId, null);
    }

    @RequiresPermissions("carbon:report:edit")
    @PostMapping("/tasks/{id}/prefill/preview")
    public AjaxResult prefillPreview(@PathVariable Long id, @RequestBody(required = false) CreateReportRequest body)
    {
        Long calcId = body == null ? null : body.getCalculationTemplateId();
        return success(reportSourceService.preview(id, reportSubjects.reportDept(id), calcId));
    }

    @RequiresPermissions("carbon:report:edit")
    @PostMapping("/tasks/{id}/prefill/commit")
    public AjaxResult prefillCommit(@PathVariable Long id, @RequestBody(required = false) CreateReportRequest body)
    {
        Long calcId = body == null ? null : body.getCalculationTemplateId();
        return success(reportSourceService.commitReviewed(id, reportSubjects.reportDept(id), calcId,
                body == null ? null : body.getVersion(), body == null ? null : body.getPreviewHash(),
                body != null && Boolean.TRUE.equals(body.getAcceptPartial())));
    }

    @RequiresPermissions("carbon:report:validate")
    @PostMapping("/tasks/{id}/validate")
    public AjaxResult validate(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body)
    {
        ReportDraft draft = reportTaskService.getDraft(id, reportSubjects.reportDept(id));
        Map<String, Object> result = reportPreflight.inspect(draft);
        boolean aiEnabled = body != null && Boolean.parseBoolean(String.valueOf(body.getOrDefault("aiEnabled", false)));
        if (aiEnabled)
        {
            try
            {
                reportGenerationService.testLlmConnection(reportLlmConfigService.resolve(asMap(body.get("llmConfig"))));
                result.put("llmReady", true);
            }
            catch (ServiceException ex)
            {
                @SuppressWarnings("unchecked")
                List<String> mustFix = (List<String>) result.get("mustFix");
                mustFix.add("AI 连通性校验失败：" + ex.getMessage());
                result.put("ok", false);
                result.put("llmReady", false);
            }
        }
        return success(result);
    }

    @RequiresPermissions("carbon:report:validate")
    @GetMapping("/llm-config")
    public AjaxResult llmConfig()
    {
        return success(reportLlmConfigService.publicSettings(SecurityUtils.isAdmin()));
    }

    @RequiresPermissions("carbon:report:validate")
    @PutMapping("/llm-config/default")
    public AjaxResult saveLlmConfigDefault(@RequestBody Map<String, Object> body)
    {
        if (!SecurityUtils.isAdmin()) throw new ServiceException("仅管理员可以设置 AI 全局默认值", HttpStatus.FORBIDDEN);
        reportLlmConfigService.saveDefault(body, SecurityUtils.getUsername());
        return success(reportLlmConfigService.publicSettings(true));
    }

    @RequiresPermissions("carbon:report:generate")
    @PostMapping("/tasks/{id}/generation-jobs")
    public AjaxResult generate(@PathVariable Long id, @RequestBody Map<String, Object> body)
    {
        String kind = String.valueOf(body.getOrDefault("outputKind", "docx"));
        boolean ai = Boolean.parseBoolean(String.valueOf(body.getOrDefault("aiEnabled", false)));
        boolean useDefaultFactors = Boolean.parseBoolean(String.valueOf(body.getOrDefault("useDefaultFactors", false)));
        LlmRuntimeConfig llmConfig = ai ? reportLlmConfigService.resolve(asMap(body.get("llmConfig"))) : null;
        return success(reportGenerationService.create(id, reportSubjects.reportDept(id), kind, ai, useDefaultFactors, llmConfig));
    }

    @RequiresPermissions("carbon:report:generate")
    @GetMapping("/tasks/{id}/factor-plan")
    public AjaxResult factorPlan(@PathVariable Long id)
    {
        return success(reportGenerationService.factorPlan(id, reportSubjects.reportDept(id)));
    }

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/tasks/{id}/generation-jobs/latest")
    public AjaxResult latestJob(@PathVariable Long id)
    {
        return success(reportGenerationService.latest(id, reportSubjects.reportDept(id)));
    }

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/tasks/{id}/generation-jobs/{jobId}")
    public AjaxResult job(@PathVariable Long id, @PathVariable Long jobId)
    {
        return success(reportGenerationService.get(id, jobId, reportSubjects.reportDept(id)));
    }

    @RequiresPermissions("carbon:report:download")
    @GetMapping("/artifacts/{id}/download")
    public ResponseEntity<InputStreamResource> download(@PathVariable Long id)
    {
        ReportFile meta = reportGenerationService.downloadMeta(id, reportSubjects.artifactDept(id));
        InputStreamResource body = new InputStreamResource(reportGenerationService.downloadStream(id, reportSubjects.artifactDept(id)));
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, org.springframework.http.ContentDisposition.attachment()
                        .filename(meta.getOriginalName(), java.nio.charset.StandardCharsets.UTF_8).build().toString())
                .contentType(MediaType.parseMediaType(meta.getMimeType() == null ? "application/octet-stream" : meta.getMimeType()))
                .body(body);
    }

    @RequiresPermissions("carbon:report:profile:query")
    @GetMapping("/dept-profile/{deptId}")
    public AjaxResult profile(@PathVariable Long deptId)
    {
        return success(reportDeptProfileService.get(currentDept(deptId)));
    }

    @RequiresPermissions("carbon:report:profile:edit")
    @PutMapping("/dept-profile/{deptId}")
    public AjaxResult saveProfile(@PathVariable Long deptId, @RequestBody ReportDeptProfile profile)
    {
        return success(reportDeptProfileService.save(profile, currentDept(deptId), SecurityUtils.getUsername()));
    }

    @RequiresPermissions("carbon:report:profile:edit")
    @Log(title = "碳排放报告档案", businessType = BusinessType.UPDATE)
    @PutMapping("/dept-profile/{deptId}/activity-prose")
    public AjaxResult saveActivityProse(@PathVariable Long deptId, @RequestBody Map<String, Object> body)
    {
        Object data = body == null ? null : body.getOrDefault("data", body);
        String payload = data == null ? "{}" : JSON.toJSONString(data);
        return success(reportDeptProfileService.saveActivityProse(currentDept(deptId), payload, SecurityUtils.getUsername()));
    }

    @RequiresPermissions("carbon:report:query")
    @GetMapping("/default-images/{role}")
    public ResponseEntity<?> defaultImage(@PathVariable String role, @RequestParam(required = false) Long deptId)
    {
        if (!ReportImageSlots.isRole(role))
        {
            throw new ServiceException("不支持的图片角色", HttpStatus.BAD_REQUEST);
        }
        ReportFile file = reportTaskService.defaultImage(currentDept(deptId), role);
        if (file == null || file.getContent() == null || file.getContent().length == 0)
        {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("code", HttpStatus.NOT_FOUND);
            body.put("msg", "未配置默认图");
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(body);
        }
        String mime = file.getMimeType() == null || file.getMimeType().isBlank()
                ? ReportImageSlots.requireSlot(role).mimeType : file.getMimeType();
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(mime))
                .header(HttpHeaders.CACHE_CONTROL, "private, max-age=3600")
                .body(file.getContent());
    }

    @RequiresPermissions("carbon:report:edit")
    @Log(title = "碳排放报告", businessType = BusinessType.UPDATE)
    @PostMapping(value = "/tasks/{id}/images/{role}", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public AjaxResult uploadImage(@PathVariable Long id, @PathVariable String role, @RequestParam("file") MultipartFile file)
    {
        if (file == null || file.isEmpty())
        {
            throw new ServiceException("请选择图片", HttpStatus.BAD_REQUEST);
        }
        try
        {
            return success(reportTaskService.uploadImage(id, reportSubjects.reportDept(id), role, file.getOriginalFilename(),
                    file.getContentType(), file.getSize(), file.getInputStream(), SecurityUtils.getUsername()));
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("上传图片失败: " + ex.getMessage());
        }
    }

    @RequiresPermissions("carbon:report:edit")
    @DeleteMapping("/tasks/{id}/images/{role}")
    public AjaxResult resetImage(@PathVariable Long id, @PathVariable String role)
    {
        reportTaskService.resetImage(id, reportSubjects.reportDept(id), role);
        return success();
    }

    @RequiresPermissions("carbon:report:add")
    @GetMapping("/subjects")
    public AjaxResult subjects()
    {
        return success(reportSubjects.list());
    }

    @RequiresPermissions("carbon:report:profile:edit")
    @GetMapping("/subject-nodes")
    public AjaxResult subjectNodes()
    {
        return success(reportSubjects.nodes());
    }

    @RequiresPermissions("carbon:report:profile:edit")
    @Log(title = "报告主体配置", businessType = BusinessType.UPDATE)
    @PutMapping("/subjects/{deptId}")
    public AjaxResult saveSubject(@PathVariable Long deptId, @RequestBody ReportDeptSubject subject)
    {
        reportSubjects.save(deptId, subject, SecurityUtils.getUsername());
        return success();
    }

    private Long currentDept(Long requested)
    {
        Long userDept = SecurityUtils.getLoginUser().getSysUser().getDeptId();
        return reportSubjects.requireDept(requested == null ? userDept : requested);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value)
    {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : Map.of();
    }
}
