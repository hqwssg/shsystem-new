package com.ruoyi.carbon.energy.cli;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.energy.config.EnergyProperties;
import com.ruoyi.common.core.exception.ServiceException;

@Component
public class EnergyCliClient
{
    private final EnergyProperties properties;

    public EnergyCliClient(EnergyProperties properties)
    {
        this.properties = properties;
    }

    public JSONObject importData(Path sourceDir, String projectCode, String projectName, String routeName,
            String versionCode, String dataStatus, String sourceNote)
    {
        List<String> command = baseCommand();
        command.add("import-data");
        command.add("--source-dir");
        command.add(sourceDir.toAbsolutePath().toString());
        command.add("--project-code");
        command.add(projectCode);
        command.add("--project-name");
        command.add(projectName);
        command.add("--route-name");
        command.add(routeName);
        command.add("--version-code");
        command.add(versionCode);
        command.add("--data-status");
        command.add(dataStatus == null || dataStatus.isBlank() ? "planning_placeholder" : dataStatus);
        if (sourceNote != null && !sourceNote.isBlank())
        {
            command.add("--source-note");
            command.add(sourceNote);
        }
        return run(command, properties.getTimeoutSeconds());
    }

    public JSONObject importExcel(Path excelDir, String baseProjectCode, String baseVersionCode, String projectCode,
            String projectName, String routeName, String versionCode, String dataStatus, String sourceNote)
    {
        List<String> command = baseCommand();
        command.add("import-excel");
        command.add("--excel-dir");
        command.add(excelDir.toAbsolutePath().toString());
        command.add("--base-project-code");
        command.add(baseProjectCode);
        command.add("--base-version-code");
        command.add(baseVersionCode);
        command.add("--project-code");
        command.add(projectCode);
        command.add("--project-name");
        command.add(projectName);
        command.add("--route-name");
        command.add(routeName);
        command.add("--version-code");
        command.add(versionCode);
        command.add("--data-status");
        command.add(dataStatus == null || dataStatus.isBlank() ? "planning_placeholder" : dataStatus);
        if (sourceNote != null && !sourceNote.isBlank())
        {
            command.add("--source-note");
            command.add(sourceNote);
        }
        return run(command, properties.getTimeoutSeconds());
    }

    public JSONObject versionTables(String projectCode, String versionCode, String topic, String sheet)
    {
        List<String> command = baseCommand();
        command.add("version-tables");
        command.add("--project-code");
        command.add(projectCode);
        command.add("--version-code");
        command.add(versionCode);
        command.add("--topic");
        command.add(topic);
        if (sheet != null && !sheet.isBlank())
        {
            command.add("--sheet");
            command.add(sheet.trim());
        }
        return run(command, properties.getTimeoutSeconds());
    }

    public JSONObject replaceVersionTables(String projectCode, String versionCode, String topic, String tablesJson,
            String sourceNote)
    {
        Path tablesFile = null;
        try
        {
            Path directory = Path.of(properties.getUploadDir()).toAbsolutePath().normalize();
            Files.createDirectories(directory);
            tablesFile = Files.createTempFile(directory, "energy-tables-", ".json");
            Files.writeString(tablesFile, tablesJson == null || tablesJson.isBlank() ? "{\"sheets\":[]}" : tablesJson,
                    StandardCharsets.UTF_8);
            List<String> command = baseCommand();
            command.add("replace-version-tables");
            command.add("--project-code");
            command.add(projectCode);
            command.add("--version-code");
            command.add(versionCode);
            command.add("--topic");
            command.add(topic);
            command.add("--tables-file");
            command.add(tablesFile.toAbsolutePath().toString());
            if (sourceNote != null && !sourceNote.isBlank())
            {
                command.add("--source-note");
                command.add(sourceNote);
            }
            return run(command, properties.getTimeoutSeconds());
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("无法写入在线编辑表格: " + ex.getMessage());
        }
        finally
        {
            if (tablesFile != null)
            {
                try
                {
                    Files.deleteIfExists(tablesFile);
                }
                catch (IOException ignored)
                {
                }
            }
        }
    }

    public JSONObject writeExcelTemplates(Path outputDir)
    {
        List<String> command = baseCommand();
        command.add("excel-templates");
        command.add("--output-dir");
        command.add(outputDir.toAbsolutePath().toString());
        return run(command, properties.getTimeoutSeconds());
    }

    public JSONObject createRun(String projectCode, String versionCode, String runType, String parametersJson,
            String requestedBy, String idempotencyKey)
    {
        Path parametersFile = null;
        try
        {
            parametersFile = writeParametersFile(Path.of(properties.getUploadDir()).toAbsolutePath().normalize(),
                    parametersJson);
            List<String> command = baseCommand();
            command.add("create-run");
            command.add("--project-code");
            command.add(projectCode);
            command.add("--version-code");
            command.add(versionCode);
            command.add("--run-type");
            command.add(runType);
            command.add("--parameters-file");
            command.add(parametersFile.toAbsolutePath().toString());
            command.add("--requested-by");
            command.add(requestedBy);
            command.add("--idempotency-key");
            command.add(idempotencyKey);
            return run(command, properties.getTimeoutSeconds());
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("无法写入任务参数文件: " + ex.getMessage());
        }
        finally
        {
            if (parametersFile != null)
            {
                try
                {
                    Files.deleteIfExists(parametersFile);
                }
                catch (IOException ignored)
                {
                }
            }
        }
    }

    public JSONObject cancelRun(String runId, String reason)
    {
        List<String> command = baseCommand();
        command.add("cancel-run");
        command.add("--run-id");
        command.add(runId);
        command.add("--reason");
        command.add(reason == null ? "cancelled_by_platform" : reason);
        return run(command, properties.getTimeoutSeconds());
    }

    public JSONObject deleteRun(String runId)
    {
        List<String> command = baseCommand();
        command.add("delete-run");
        command.add("--run-id");
        command.add(runId);
        return run(command, properties.getTimeoutSeconds());
    }

    public JSONObject workerOnce(String runId)
    {
        List<String> command = baseCommand();
        command.add("worker-once");
        command.add("--run-id");
        command.add(runId);
        command.add("--lease-seconds");
        command.add(String.valueOf(Math.max(300, properties.getSolveTimeoutSeconds())));
        command.add("--heartbeat-interval-seconds");
        command.add("60");
        command.add("--resource-profile");
        command.add(properties.getResourceProfile());
        return run(command, properties.getSolveTimeoutSeconds());
    }

    public JSONObject recoverExpired()
    {
        List<String> command = baseCommand();
        command.add("recover-expired");
        command.add("--max-attempts");
        command.add("3");
        return run(command, properties.getTimeoutSeconds());
    }

    private List<String> baseCommand()
    {
        if (properties.getProjectRoot() == null || properties.getProjectRoot().isBlank())
        {
            throw new ServiceException("未配置 carbon.energy.project-root / ENERGY_PROJECT_ROOT");
        }
        List<String> command = new ArrayList<>();
        command.add(properties.getPythonExecutable());
        command.add("-m");
        command.add("database.cli");
        return command;
    }

    JSONObject run(List<String> command, int timeoutSeconds)
    {
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(Path.of(properties.getProjectRoot()).toFile());
        Map<String, String> env = builder.environment();
        env.put("PYTHONPATH", properties.getProjectRoot());
        env.put("PYTHONIOENCODING", "utf-8");
        env.put("ENERGY_DATABASE_URL", properties.resolveDatabaseUrl());
        ExecutorService io = Executors.newFixedThreadPool(2);
        try
        {
            Process process = builder.start();
            Future<String> stdout = io.submit(() -> new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8));
            Future<String> stderr = io.submit(() -> new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8));
            boolean finished = process.waitFor(Duration.ofSeconds(Math.max(5, timeoutSeconds)).toSeconds(),
                    TimeUnit.SECONDS);
            if (!finished)
            {
                process.destroyForcibly();
                throw new ServiceException("能量任务命令超时");
            }
            String out = stdout.get(5, TimeUnit.SECONDS);
            String err = stderr.get(5, TimeUnit.SECONDS);
            if (process.exitValue() != 0)
            {
                throw new ServiceException(cliErrorMessage(err.isBlank() ? out : err));
            }
            String payload = out.trim();
            if (payload.isEmpty())
            {
                return new JSONObject();
            }
            return JSON.parseObject(payload);
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("无法启动能量任务进程: " + ex.getMessage());
        }
        finally
        {
            io.shutdownNow();
        }
    }

    static Path writeParametersFile(Path directory, String parametersJson) throws IOException
    {
        Files.createDirectories(directory);
        Path file = Files.createTempFile(directory, "energy-params-", ".json");
        Files.writeString(file, parametersJson == null || parametersJson.isBlank() ? "{}" : parametersJson,
                StandardCharsets.UTF_8);
        return file;
    }

    static String cliErrorMessage(String text)
    {
        if (text == null || text.isBlank())
        {
            return "能量任务命令失败";
        }
        String trimmed = text.trim();
        if (!trimmed.contains("Traceback"))
        {
            return trimmed;
        }
        String[] lines = trimmed.split("\\r?\\n");
        for (int i = lines.length - 1; i >= 0; i--)
        {
            String line = lines[i].trim();
            if (!line.isEmpty())
            {
                return line;
            }
        }
        return "能量任务命令失败";
    }
}
