package com.ruoyi.carbon.energy.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import com.ruoyi.carbon.energy.controller.EnergyReportExportController;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.security.annotation.RequiresPermissions;

class EnergyDocumentExporterTest
{
    @TempDir Path temp;

    @Test
    void archivedSourcesAndImagesAreAuthorizedAndTempFilesRemoved() throws Exception
    {
        var energy = mock(IEnergyService.class);
        when(energy.downloadMeta(17L, "run", "DISPATCH_CASE_REPORT.md"))
            .thenReturn(Map.of("content", "# 标题\n![图](figures/a.png)".getBytes(StandardCharsets.UTF_8)));
        when(energy.artifacts(17L, "run")).thenReturn(List.of(
            Map.of("relativePath", "DISPATCH_CASE_REPORT.md"), Map.of("relativePath", "figures/a.png")));
        when(energy.downloadMeta(17L, "run", "figures/a.png")).thenReturn(Map.of("content", new byte[]{1, 2}));
        Path[] folder = new Path[1];
        var exporter = new EnergyDocumentExporter(energy) {
            @Override void convert(Path manifest, Path output, Path log) throws Exception {
                folder[0] = manifest.getParent();
                String json = Files.readString(manifest);
                assertTrue(json.contains("重空调度报告"));
                assertTrue(Files.exists(folder[0].resolve("input/figures/a.png")));
                Files.write(output, new byte[]{3, 4});
            }
        };
        var result = exporter.export(17L, "run", "DISPATCH_CASE_REPORT.md", "pdf");
        assertEquals("重空调度报告.pdf", result.filename());
        assertEquals("application/pdf", result.mediaType());
        assertArrayEquals(new byte[]{3, 4}, result.content());
        assertFalse(Files.exists(folder[0]));
        verify(energy).downloadMeta(17L, "run", "figures/a.png");
    }

    @Test
    void permissionsAndInputChecksCannotBeBypassed() throws Exception
    {
        var energy = mock(IEnergyService.class);
        var exporter = new EnergyDocumentExporter(energy);
        assertThrows(ServiceException.class, () -> exporter.export(17L, "run", "x.csv", "pdf"));
        assertThrows(ServiceException.class, () -> exporter.export(17L, "run", "x.md", "exe"));
        verifyNoInteractions(energy);
        when(energy.downloadMeta(17L, "other", "x.md")).thenThrow(new ServiceException("forbidden"));
        assertThrows(ServiceException.class, () -> exporter.export(17L, "other", "x.md", "docx"));
        verify(energy, never()).artifacts(any(), any());
        assertThrows(ServiceException.class, () -> EnergyDocumentExporter.stage(temp, "../outside.png", new byte[0]));
        var method = EnergyReportExportController.class.getMethod("export", String.class, String.class, String.class);
        assertEquals("carbon:energy:download", method.getAnnotation(RequiresPermissions.class).value()[0]);
    }
}
