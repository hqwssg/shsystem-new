package com.ruoyi.carbon.energy.controller;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;
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
import com.ruoyi.carbon.energy.service.EnergyAccessGuard;
import com.ruoyi.carbon.energy.service.IEnergyService;
import com.ruoyi.common.core.web.controller.BaseController;
import com.ruoyi.common.core.web.domain.AjaxResult;
import com.ruoyi.common.log.annotation.Log;
import com.ruoyi.common.log.enums.BusinessType;
import com.ruoyi.common.security.annotation.RequiresPermissions;
import com.ruoyi.common.security.utils.SecurityUtils;

@RestController
@RequestMapping("/carbon/energy")
public class EnergyController extends BaseController
{
    private final IEnergyService energyService;

    public EnergyController(IEnergyService energyService)
    {
        this.energyService = energyService;
    }

    @RequiresPermissions("carbon:energy:list")
    @GetMapping("/bindings")
    public AjaxResult bindings()
    {
        return success(energyService.listBindings(currentDept()));
    }

    @RequiresPermissions("carbon:energy:project")
    @Log(title = "能量项目对照", businessType = BusinessType.INSERT)
    @PostMapping("/bindings")
    public AjaxResult bind(@RequestBody Map<String, Object> body)
    {
        return success(energyService.bindProject(currentDept(), string(body.get("projectCode")), SecurityUtils.getUsername()));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/versions")
    public AjaxResult versions()
    {
        return success(energyService.listVersions(currentDept()));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/version-files")
    public AjaxResult versionFiles(@RequestParam String projectCode, @RequestParam String versionCode)
    {
        return success(energyService.listVersionFiles(currentDept(), projectCode, versionCode));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/parameter-preset")
    public AjaxResult parameterPreset(@RequestParam String projectCode, @RequestParam String versionCode,
            @RequestParam String runType)
    {
        return success(energyService.parameterPreset(currentDept(), projectCode, versionCode, runType));
    }

    @RequiresPermissions("carbon:energy:version")
    @Log(title = "能量数据版本", businessType = BusinessType.INSERT)
    @PostMapping(value = "/versions", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public AjaxResult publish(@RequestParam String projectCode, @RequestParam String projectName,
            @RequestParam String routeName, @RequestParam String versionCode,
            @RequestParam(required = false) String dataStatus, @RequestParam(required = false) String sourceNote,
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam(value = "relativePaths", required = false) List<String> relativePaths)
    {
        return success(energyService.publishVersion(currentDept(), SecurityUtils.getUsername(), projectCode, projectName,
                routeName, versionCode, dataStatus, sourceNote, files, relativePaths));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/excel-templates")
    public AjaxResult excelTemplates()
    {
        return success(energyService.listExcelTemplates());
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/excel-templates/{code}")
    public ResponseEntity<InputStreamResource> excelTemplate(@PathVariable String code) throws Exception
    {
        Path file = energyService.excelTemplateFile(code);
        String filename = file.getFileName().toString();
        String encoded = URLEncoder.encode(filename, StandardCharsets.UTF_8).replace("+", "%20");
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + code + ".xlsx\"; filename*=UTF-8''" + encoded)
                .contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .contentLength(Files.size(file))
                .body(new InputStreamResource(Files.newInputStream(file)));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/excel-template-zip")
    public ResponseEntity<byte[]> excelTemplateZip()
    {
        byte[] zip = energyService.excelTemplateZip();
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"energy-excel-templates.zip\"")
                .contentType(MediaType.parseMediaType("application/zip"))
                .body(zip);
    }

    @RequiresPermissions("carbon:energy:version")
    @Log(title = "能量Excel数据版本", businessType = BusinessType.INSERT)
    @PostMapping(value = "/versions/excel", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public AjaxResult publishExcel(@RequestParam String projectCode, @RequestParam String projectName,
            @RequestParam String routeName, @RequestParam String versionCode,
            @RequestParam String baseProjectCode, @RequestParam String baseVersionCode,
            @RequestParam(required = false) String dataStatus, @RequestParam(required = false) String sourceNote,
            @RequestParam("files") List<MultipartFile> files)
    {
        return success(energyService.publishExcelVersion(currentDept(), SecurityUtils.getUsername(), projectCode,
                projectName, routeName, versionCode, dataStatus, sourceNote, baseProjectCode, baseVersionCode, files));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/version-tables")
    public AjaxResult versionTables(@RequestParam String projectCode, @RequestParam String versionCode,
            @RequestParam String topic, @RequestParam(required = false) String sheet)
    {
        return success(energyService.versionTables(currentDept(), projectCode, versionCode, topic, sheet));
    }

    @RequiresPermissions("carbon:energy:version")
    @Log(title = "能量数据版本在线编辑", businessType = BusinessType.UPDATE)
    @PutMapping("/version-tables")
    public AjaxResult replaceVersionTables(@RequestBody Map<String, Object> body)
    {
        return success(energyService.replaceVersionTables(currentDept(), string(body.get("projectCode")),
                string(body.get("versionCode")), string(body.get("topic")), string(body.get("sourceNote")),
                body.get("sheets")));
    }

    @RequiresPermissions("carbon:energy:list")
    @GetMapping("/runs")
    public AjaxResult runs(@RequestParam(required = false) String runType, @RequestParam(required = false) String status)
    {
        return success(energyService.listRuns(currentDept(), runType, status));
    }

    @RequiresPermissions("carbon:energy:run")
    @Log(title = "能量算法任务", businessType = BusinessType.INSERT)
    @PostMapping("/runs")
    public AjaxResult create(@RequestBody Map<String, Object> body)
    {
        String runType = EnergyAccessGuard.requireRunType(string(body.get("runType")));
        String params = body.get("parameters") == null ? "{}" : String.valueOf(body.get("parameters") instanceof String
                ? body.get("parameters")
                : com.alibaba.fastjson2.JSON.toJSONString(body.get("parameters")));
        String key = string(body.get("idempotencyKey"));
        if (key == null || key.isBlank())
        {
            key = UUID.randomUUID().toString();
        }
        return success(energyService.createRun(currentDept(), SecurityUtils.getUsername(), string(body.get("projectCode")),
                string(body.get("versionCode")), runType, params, key));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}")
    public AjaxResult get(@PathVariable String runId)
    {
        return success(energyService.getRun(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:cancel")
    @Log(title = "能量算法任务", businessType = BusinessType.UPDATE)
    @PostMapping("/runs/{runId}/cancel")
    public AjaxResult cancel(@PathVariable String runId, @RequestBody(required = false) Map<String, Object> body)
    {
        String reason = body == null ? null : string(body.get("reason"));
        return success(energyService.cancelRun(currentDept(), runId, reason));
    }

    @RequiresPermissions("carbon:energy:remove")
    @Log(title = "能量算法任务", businessType = BusinessType.DELETE)
    @DeleteMapping("/runs/{runId}")
    public AjaxResult remove(@PathVariable String runId)
    {
        return success(energyService.deleteRun(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/storage-planning")
    public AjaxResult storagePlanning(@PathVariable String runId,
            @RequestParam(required = false) String planId,
            @RequestParam(defaultValue = "1") int pageNum,
            @RequestParam(defaultValue = "20") int pageSize)
    {
        return success(energyService.storagePlanning(currentDept(), runId, planId, pageNum, pageSize));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/summary")
    public AjaxResult summary(@PathVariable String runId)
    {
        return success(energyService.summary(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/timetable")
    public AjaxResult timetable(@PathVariable String runId)
    {
        return success(energyService.timetable(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/optimization")
    public AjaxResult optimization(@PathVariable String runId)
    {
        return success(energyService.optimization(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/rolling")
    public AjaxResult rolling(@PathVariable String runId)
    {
        return success(energyService.rolling(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/robustness")
    public AjaxResult robustness(@PathVariable String runId)
    {
        return success(energyService.robustness(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:query")
    @GetMapping("/runs/{runId}/artifacts")
    public AjaxResult artifacts(@PathVariable String runId)
    {
        return success(energyService.artifacts(currentDept(), runId));
    }

    @RequiresPermissions("carbon:energy:download")
    @GetMapping("/artifacts")
    public ResponseEntity<InputStreamResource> download(@RequestParam String runId, @RequestParam String path)
    {
        Map<String, Object> meta = energyService.downloadMeta(currentDept(), runId, path);
        String name = String.valueOf(meta.getOrDefault("relativePath", "artifact.bin"));
        String media = String.valueOf(meta.getOrDefault("mediaType", "application/octet-stream"));
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + Path.of(name).getFileName() + "\"")
                .contentType(MediaType.parseMediaType(media))
                .body(new InputStreamResource(energyService.downloadStream(currentDept(), runId, path)));
    }

    private Long currentDept()
    {
        if (SecurityUtils.isAdmin())
        {
            return null;
        }
        return SecurityUtils.getLoginUser().getSysUser().getDeptId();
    }

    private static String string(Object value)
    {
        return value == null ? null : String.valueOf(value);
    }
}
