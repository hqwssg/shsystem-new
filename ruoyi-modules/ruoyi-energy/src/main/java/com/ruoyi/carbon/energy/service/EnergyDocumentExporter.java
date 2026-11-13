package com.ruoyi.carbon.energy.service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;
import com.alibaba.fastjson2.JSON;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.core.utils.PythonServiceClient;

@Service
public class EnergyDocumentExporter
{
    private final IEnergyService energy;
    @Value("${carbon.report.renderer.python-executable:${ENERGY_PYTHON:python}}")
    private String python;
    @Value("${carbon.report.renderer.module-root:${CARBON_REPORT_RENDERER_ROOT:.}}")
    private String moduleRoot;
    @Value("${carbon.report.renderer.soffice-path:}")
    private String soffice;
    @Value("${carbon.report.renderer.work-dir:${java.io.tmpdir}/carbon-report-work}")
    private String workRoot;

    public EnergyDocumentExporter(IEnergyService energy) { this.energy = energy; }

    public record ExportedDocument(byte[] content, String filename, String mediaType) { }

    public ExportedDocument export(Long dept, String runId, String path, String format)
    {
        PythonServiceClient.requireConfigured();
        if (!List.of("docx", "pdf").contains(format) || path == null || !path.toLowerCase(Locale.ROOT).endsWith(".md"))
            throw new ServiceException("请选择Markdown报告并使用Word或PDF格式");
        // Authorization precedes reading or staging any source/related artifact.
        Map<String, Object> source = energy.downloadMeta(dept, runId, path);
        List<Map<String, Object>> artifacts = energy.artifacts(dept, runId);
        Path work = null;
        try
        {
            Map<String, Object> names;
            try (var input = new ClassPathResource("energy-report-names.json").getInputStream())
            {
                names = JSON.parseObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
            }
            if (PythonServiceClient.enabled())
            {
                Path root = Path.of(workRoot).toAbsolutePath().normalize();
                Files.createDirectories(root);
                work = Files.createTempDirectory(root, "energy-report-export-");
            }
            else work = Files.createTempDirectory("energy-report-export-");
            Path input = work.resolve("input");
            Files.createDirectories(input);
            stage(input, path, source.get("content"));
            List<String> paths = new ArrayList<>();
            for (Map<String, Object> artifact : artifacts)
            {
                String relative = String.valueOf(artifact.get("relativePath"));
                paths.add(relative.replace('\\', '/'));
                if (relative.toLowerCase(Locale.ROOT).matches(".*\\.(png|jpg|jpeg|gif|bmp|webp|svg)"))
                    stage(input, relative, energy.downloadMeta(dept, runId, relative).get("content"));
            }
            Map<String, Object> manifest = new LinkedHashMap<>();
            manifest.put("root", input.toString());
            manifest.put("source", path.replace('\\', '/'));
            manifest.put("artifacts", paths);
            manifest.put("names", names);
            Path request = work.resolve("manifest.json");
            Files.writeString(request, JSON.toJSONString(manifest), StandardCharsets.UTF_8);
            Path output = work.resolve("report." + format);
            convert(request, output, work.resolve("conversion.log"));
            if (!Files.isRegularFile(output) || Files.size(output) == 0)
                throw new ServiceException("报告转换未生成文件");
            @SuppressWarnings("unchecked")
            Map<String, String> fileNames = (Map<String, String>) names.get("files");
            String base = Path.of(path.replace('\\', '/')).getFileName().toString();
            String title = fileNames.getOrDefault(base, base.substring(0, base.length() - 3));
            String filename = title.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_") + "." + format;
            return new ExportedDocument(Files.readAllBytes(output), filename,
                format.equals("pdf") ? "application/pdf" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        }
        catch (ServiceException ex) { throw ex; }
        catch (Exception ex) { throw new ServiceException("报告导出失败：" + ex.getMessage()); }
        finally
        {
            if (work != null)
            {
                try (var entries = Files.walk(work))
                {
                    for (Path entry : entries.sorted(Comparator.reverseOrder()).toList())
                        Files.deleteIfExists(entry);
                }
                catch (IOException ignored) { /* A failed cleanup must not replace the export result. */ }
            }
        }
    }

    static void stage(Path root, String relative, Object content) throws IOException
    {
        EnergyAccessGuard.requireRelativePath(relative);
        Path target = root.resolve(relative.replace('\\', '/')).normalize();
        if (!target.startsWith(root) || !(content instanceof byte[] bytes))
            throw new ServiceException("报告附件不可读或路径无效");
        Files.createDirectories(target.getParent());
        Files.write(target, bytes);
    }

    void convert(Path manifest, Path output, Path log) throws Exception
    {
        if (PythonServiceClient.enabled())
        {
            var result = PythonServiceClient.run(List.of(python, "-m", "carbon_report_agent.markdown_export",
                    "--manifest", manifest.toString(), "--output", output.toString()),
                    manifest.getParent(), Map.of(), java.time.Duration.ofSeconds(150), 1048576);
            if (result.getIntValue("exitCode") != 0)
            {
                String error = result.getString("stderr");
                throw new ServiceException(error == null || error.isBlank() ? "报告转换失败"
                        : error.substring(Math.max(0, error.length() - 1500)));
            }
            return;
        }
        ProcessBuilder builder = new ProcessBuilder(python, "-m", "carbon_report_agent.markdown_export",
            "--manifest", manifest.toString(), "--output", output.toString());
        builder.directory(Path.of(moduleRoot).toAbsolutePath().toFile());
        builder.environment().put("PYTHONPATH", Path.of(moduleRoot).toAbsolutePath().toString());
        builder.environment().put("PYTHONIOENCODING", "utf-8");
        builder.environment().put("PYTHONUTF8", "1");
        if (soffice != null && !soffice.isBlank())
            builder.environment().put("CARBON_REPORT_SOFFICE_PATH", soffice);
        builder.redirectErrorStream(true).redirectOutput(log.toFile());
        Process process = builder.start();
        try
        {
            if (!process.waitFor(150, TimeUnit.SECONDS))
                throw new ServiceException("报告转换超时，请稍后重试");
            if (process.exitValue() != 0)
            {
                String error = Files.readString(log, StandardCharsets.UTF_8).trim();
                throw new ServiceException(error.isEmpty() ? "报告转换失败" : error.substring(Math.max(0, error.length() - 1500)));
            }
        }
        finally
        {
            process.descendants().forEach(child -> child.destroyForcibly());
            if (process.isAlive()) { process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS); }
        }
    }
}
