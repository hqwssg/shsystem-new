package com.ruoyi.carbon.energy.controller;

import java.nio.charset.StandardCharsets;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import com.ruoyi.carbon.energy.service.EnergyDocumentExporter;
import com.ruoyi.common.security.annotation.RequiresPermissions;
import com.ruoyi.common.security.utils.SecurityUtils;

@RestController
@RequestMapping("/carbon/energy")
public class EnergyReportExportController
{
    private final EnergyDocumentExporter exporter;
    public EnergyReportExportController(EnergyDocumentExporter exporter) { this.exporter = exporter; }

    @RequiresPermissions("carbon:energy:download")
    @GetMapping("/artifacts/export")
    public ResponseEntity<byte[]> export(@RequestParam String runId, @RequestParam String path, @RequestParam String format)
    {
        Long dept = SecurityUtils.isAdmin() ? null : SecurityUtils.getLoginUser().getSysUser().getDeptId();
        var result = exporter.export(dept, runId, path, format);
        return ResponseEntity.ok().contentType(MediaType.parseMediaType(result.mediaType()))
            .header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename(result.filename(), StandardCharsets.UTF_8).build().toString())
            .body(result.content());
    }
}
