package com.ruoyi.carbon.energy.service.impl;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executor;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.energy.cli.EnergyCliClient;
import com.ruoyi.carbon.energy.config.EnergyProperties;
import com.ruoyi.carbon.energy.mapper.EnergyMapper;
import com.ruoyi.carbon.energy.service.EnergyAccessGuard;
import com.ruoyi.carbon.energy.service.EnergySolveDispatcher;
import com.ruoyi.carbon.energy.service.IEnergyService;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class EnergyServiceImpl implements IEnergyService
{
    private final EnergyMapper mapper;
    private final EnergyCliClient cli;
    private final EnergyProperties properties;
    private final Executor executor;

    public EnergyServiceImpl(EnergyMapper mapper, EnergyCliClient cli, EnergyProperties properties,
            @Qualifier("energyExecutor") Executor executor)
    {
        this.mapper = mapper;
        this.cli = cli;
        this.properties = properties;
        this.executor = executor;
    }

    @Override
    public List<Map<String, Object>> listBindings(Long deptId)
    {
        return mapper.selectDeptProjects(deptId);
    }

    @Override
    public Map<String, Object> bindProject(Long deptId, String projectCode, String username)
    {
        if (projectCode == null || projectCode.isBlank())
        {
            throw new ServiceException("projectCode 不能为空", HttpStatus.BAD_REQUEST);
        }
        Map<String, Object> row = new HashMap<>();
        row.put("deptId", deptId);
        row.put("projectCode", projectCode.trim());
        row.put("enabled", "1");
        row.put("createBy", username);
        mapper.insertDeptProject(row);
        return row;
    }

    @Override
    public List<Map<String, Object>> listVersions(Long deptId)
    {
        return mapper.selectVersions(deptId);
    }

    @Override
    public List<Map<String, Object>> listVersionFiles(Long deptId, String projectCode, String versionCode)
    {
        requireProjectVisible(deptId, projectCode);
        return mapper.selectVersionFiles(deptId, projectCode, versionCode);
    }

    @Override
    public Map<String, Object> parameterPreset(Long deptId, String projectCode, String versionCode, String runType)
    {
        EnergyAccessGuard.requireRunType(runType);
        requireProjectVisible(deptId, projectCode);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("storageDevices", mapper.selectStorageDevices(deptId, projectCode, versionCode));
        body.putAll(cli.planningPreset(projectCode, versionCode));
        Map<String, Object> last = mapper.selectLatestRunParameters(deptId, projectCode, versionCode, runType);
        if (last != null && last.get("parametersJson") != null)
        {
            body.put("lastRunId", last.get("runId"));
            body.put("lastQueuedAt", last.get("queuedAt"));
            body.put("lastParameters", parseJsonMap(last.get("parametersJson")));
        }
        else
        {
            body.put("lastRunId", null);
            body.put("lastQueuedAt", null);
            body.put("lastParameters", null);
        }
        return body;
    }

    @Override
    public JSONObject publishVersion(Long deptId, String username, String projectCode, String projectName,
            String routeName, String versionCode, String dataStatus, String sourceNote, List<MultipartFile> files,
            List<String> relativePaths)
    {
        requireProjectVisible(deptId, projectCode);
        if (files == null || files.isEmpty())
        {
            throw new ServiceException("请至少上传一个输入文件", HttpStatus.BAD_REQUEST);
        }
        try
        {
            Path root = Files.createDirectories(resolveUploadRoot().resolve(UUID.randomUUID().toString()));
            for (int i = 0; i < files.size(); i++)
            {
                MultipartFile file = files.get(i);
                String submitted = relativePaths != null && i < relativePaths.size() && relativePaths.get(i) != null
                        && !relativePaths.get(i).isBlank() ? relativePaths.get(i) : file.getOriginalFilename();
                String relative = EnergyAccessGuard.relativePath(submitted);
                Path target = root.resolve(relative).normalize();
                if (!target.startsWith(root))
                {
                    throw new ServiceException("非法文件路径", HttpStatus.BAD_REQUEST);
                }
                Files.createDirectories(target.getParent());
                file.transferTo(target);
            }
            return cli.importData(root, projectCode, projectName, routeName, versionCode, dataStatus, sourceNote);
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("发布数据版本失败: " + ex.getMessage());
        }
    }

    @Override
    public JSONObject publishExcelVersion(Long deptId, String username, String projectCode, String projectName,
            String routeName, String versionCode, String dataStatus, String sourceNote, String baseProjectCode,
            String baseVersionCode, List<MultipartFile> files)
    {
        if (baseProjectCode == null || baseProjectCode.isBlank() || baseVersionCode == null || baseVersionCode.isBlank())
        {
            throw new ServiceException("请选择基于哪个已有版本", HttpStatus.BAD_REQUEST);
        }
        requireProjectVisible(deptId, baseProjectCode);
        if (files == null || files.isEmpty())
        {
            throw new ServiceException("请至少上传一个 Excel 文件", HttpStatus.BAD_REQUEST);
        }
        try
        {
            Path root = Files.createDirectories(resolveUploadRoot().resolve(UUID.randomUUID().toString()));
            Set<String> usedNames = new HashSet<>();
            for (MultipartFile file : files)
            {
                String original = file.getOriginalFilename() == null ? "upload.xlsx" : file.getOriginalFilename();
                String name = Path.of(original).getFileName().toString();
                if (!name.toLowerCase().endsWith(".xlsx"))
                {
                    throw new ServiceException("只接受 .xlsx 文件：" + name, HttpStatus.BAD_REQUEST);
                }
                if (!usedNames.add(name))
                {
                    throw new ServiceException("上传文件名重复：" + name, HttpStatus.BAD_REQUEST);
                }
                file.transferTo(root.resolve(name));
            }
            if (deptId != null)
            {
                bindProject(deptId, projectCode, username);
            }
            return cli.importExcel(root, baseProjectCode.trim(), baseVersionCode.trim(), projectCode, projectName,
                    routeName, versionCode, dataStatus, sourceNote);
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("按 Excel 发布失败: " + ex.getMessage());
        }
    }

    @Override
    public JSONObject versionTables(Long deptId, String projectCode, String versionCode, String topic, String sheet)
    {
        requireVersionTopic(projectCode, versionCode, topic);
        requireProjectVisible(deptId, projectCode);
        return cli.versionTables(projectCode.trim(), versionCode.trim(), topic.trim(), sheet);
    }

    @Override
    public JSONObject replaceVersionTables(Long deptId, String projectCode, String versionCode, String topic,
            String sourceNote, Object sheets)
    {
        requireVersionTopic(projectCode, versionCode, topic);
        requireProjectVisible(deptId, projectCode);
        if (!(sheets instanceof List<?> rows) || rows.isEmpty())
        {
            throw new ServiceException("请提交要保存的表格", HttpStatus.BAD_REQUEST);
        }
        JSONObject payload = new JSONObject();
        payload.put("sheets", sheets);
        return cli.replaceVersionTables(projectCode.trim(), versionCode.trim(), topic.trim(), payload.toJSONString(),
                sourceNote);
    }

    @Override
    public List<Map<String, Object>> listExcelTemplates()
    {
        return readExcelCatalog();
    }

    @Override
    public Path excelTemplateFile(String code)
    {
        Map<String, Object> item = findExcelTemplate(code);
        Path file = excelTemplateDir().resolve(String.valueOf(item.get("filename")));
        if (!Files.isRegularFile(file))
        {
            throw new ServiceException("模板文件不存在: " + item.get("filename"), HttpStatus.NOT_FOUND);
        }
        return file;
    }

    @Override
    public byte[] excelTemplateZip()
    {
        try (ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                ZipOutputStream zip = new ZipOutputStream(buffer, StandardCharsets.UTF_8))
        {
            for (Map<String, Object> item : readExcelCatalog())
            {
                Path file = excelTemplateDir().resolve(String.valueOf(item.get("filename")));
                if (!Files.isRegularFile(file))
                {
                    continue;
                }
                zip.putNextEntry(new ZipEntry(String.valueOf(item.get("filename"))));
                Files.copy(file, zip);
                zip.closeEntry();
            }
            zip.finish();
            return buffer.toByteArray();
        }
        catch (Exception ex)
        {
            throw new ServiceException("打包 Excel 模板失败: " + ex.getMessage());
        }
    }

    private Path excelTemplateDir()
    {
        Path dir = com.ruoyi.common.core.utils.PythonServiceClient.enabled()
                ? Path.of(properties.getUploadDir()).toAbsolutePath().resolve("excel-templates")
                : Path.of(properties.getProjectRoot()).resolve("data_templates").resolve("user_excel");
        if (!Files.isRegularFile(dir.resolve("catalog.json")))
        {
            cli.writeExcelTemplates(dir);
        }
        return dir;
    }

    private List<Map<String, Object>> readExcelCatalog()
    {
        try
        {
            String json = Files.readString(excelTemplateDir().resolve("catalog.json"), StandardCharsets.UTF_8);
            return JSON.parseObject(json, new com.alibaba.fastjson2.TypeReference<List<Map<String, Object>>>()
            {
            });
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("读取 Excel 模板目录失败: " + ex.getMessage());
        }
    }

    private Map<String, Object> findExcelTemplate(String code)
    {
        if (code == null || code.isBlank())
        {
            throw new ServiceException("模板编码不能为空", HttpStatus.BAD_REQUEST);
        }
        for (Map<String, Object> item : readExcelCatalog())
        {
            if (code.equals(String.valueOf(item.get("code"))))
            {
                return item;
            }
        }
        throw new ServiceException("未知 Excel 模板: " + code, HttpStatus.BAD_REQUEST);
    }

    @Override
    public List<Map<String, Object>> listRuns(Long deptId, String runType, String status)
    {
        return mapper.selectRuns(deptId, runType, status);
    }

    @Override
    public JSONObject createRun(Long deptId, String username, String projectCode, String versionCode, String runType,
            String parametersJson, String idempotencyKey)
    {
        EnergyAccessGuard.requireRunType(runType);
        requireProjectVisible(deptId, projectCode);
        String key = idempotencyKey == null || idempotencyKey.isBlank() ? UUID.randomUUID().toString() : idempotencyKey.trim();
        String params = parametersJson == null || parametersJson.isBlank() ? "{}" : parametersJson;
        JSONObject created = cli.createRun(projectCode, versionCode, runType, params, username, key);
        String runId = created.getString("run_id");
        if (runId == null || runId.isBlank())
        {
            runId = created.getString("runId");
        }
        final String queuedId = runId;
        executor.execute(() -> EnergySolveDispatcher.dispatch(cli, queuedId));
        return created;
    }

    @Override
    public Map<String, Object> getRun(Long deptId, String runId)
    {
        Map<String, Object> run = requireRun(deptId, runId);
        run.put("stateEvents", mapper.selectStateEvents(runId));
        return run;
    }

    @Override
    public JSONObject cancelRun(Long deptId, String runId, String reason)
    {
        requireRun(deptId, runId);
        return cli.cancelRun(runId, reason);
    }

    @Override
    public JSONObject deleteRun(Long deptId, String runId)
    {
        requireRun(deptId, runId);
        return cli.deleteRun(runId);
    }

    @Override
    public Map<String, Object> summary(Long deptId, String runId)
    {
        requireSucceeded(deptId, runId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("auditSummary", mapper.selectAuditSummary(runId));
        body.put("decision", mapper.selectDecision(runId));
        body.put("kpis", mapper.selectKpis(runId));
        body.put("rollingEvents", mapper.selectRollingEvents(runId));
        return body;
    }

    @Override
    public Map<String, Object> storagePlanning(Long deptId, String runId, String planId, int pageNum, int pageSize)
    {
        Map<String, Object> run = requireSucceeded(deptId, runId);
        if (!"storage_planning".equals(run.get("runType")))
        {
            throw new ServiceException("该任务不是储能规划任务", HttpStatus.BAD_REQUEST);
        }
        if (pageNum < 1 || pageSize < 1 || pageSize > 100 || (long) (pageNum - 1) * pageSize > Integer.MAX_VALUE)
        {
            throw new ServiceException("分页参数无效，每页支持1至100条", HttpStatus.BAD_REQUEST);
        }
        Map<String, Object> decision = mapper.selectStoragePlanningDecision(runId);
        Map<String, Object> selected = null;
        String selectedId = planId;
        if ((selectedId == null || selectedId.isBlank()) && decision != null)
        {
            Object value = decision.get("selectedStoragePlanId");
            selectedId = value == null ? null : String.valueOf(value);
        }
        if (selectedId != null && !selectedId.isBlank())
        {
            selected = mapper.selectStoragePlan(runId, selectedId);
            if (selected == null || selected.isEmpty())
            {
                throw new ServiceException("方案不属于当前任务", HttpStatus.NOT_FOUND);
            }
        }
        if (decision != null)
        {
            decision.put("details", camelJson(parseJsonMap(decision.remove("decisionJson"))));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("decision", decision);
        body.put("plans", mapper.selectStoragePlans(runId, (pageNum - 1) * pageSize, pageSize));
        body.put("total", mapper.countStoragePlans(runId));
        body.put("pageNum", pageNum);
        body.put("pageSize", pageSize);
        body.put("selectedPlan", selected);
        body.put("devices", selected == null ? List.of() : mapper.selectStoragePlanDevices(selectedId));
        body.put("scenarioResults", selected == null ? List.of() : mapper.selectStoragePlanScenarios(selectedId));
        String baselineId = mapper.selectNoBuildStoragePlanId(runId);
        body.put("baselineScenarioResults", baselineId == null ? List.of() : mapper.selectStoragePlanScenarios(baselineId));
        body.put("referenceOnly", decision != null && "no_feasible_plan".equals(decision.get("decision")));
        unpackPlanningJson(selected);
        for (String key : List.of("plans", "devices", "scenarioResults", "baselineScenarioResults"))
        {
            for (Object item : (List<?>) body.get(key))
            {
                unpackPlanningJson((Map<String, Object>) item);
            }
        }
        return body;
    }

    private static void unpackPlanningJson(Map<String, Object> row)
    {
        if (row == null) { return; }
        for (String key : List.of("metricsJson", "deviceJson", "resultJson"))
        {
            if (row.containsKey(key))
            {
                row.put(key.substring(0, key.length() - 4), camelJson(parseJsonMap(row.remove(key))));
            }
        }
    }

    private static Object camelJson(Object value)
    {
        if (value instanceof Map<?, ?> map)
        {
            Map<String, Object> result = new LinkedHashMap<>();
            map.forEach((key, item) -> {
                StringBuilder name = new StringBuilder();
                boolean upper = false;
                for (char c : String.valueOf(key).toCharArray())
                {
                    if (c == '_') { upper = true; }
                    else { name.append(upper ? Character.toUpperCase(c) : c); upper = false; }
                }
                result.put(name.toString(), camelJson(item));
            });
            return result;
        }
        if (value instanceof List<?> list)
        {
            return list.stream().map(EnergyServiceImpl::camelJson).collect(java.util.stream.Collectors.toList());
        }
        return value;
    }

    @Override
    public Map<String, Object> timetable(Long deptId, String runId)
    {
        requireSucceeded(deptId, runId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("runningArcs", mapper.selectRunningArcs(runId));
        body.put("timeSlices", mapper.selectTimeSlices(runId));
        body.put("settlements", mapper.selectSettlements(runId));
        body.put("issues", mapper.selectIssues(runId));
        body.put("suggestions", mapper.selectSuggestions(runId));
        return body;
    }

    @Override
    public Map<String, Object> optimization(Long deptId, String runId)
    {
        requireSucceeded(deptId, runId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("decision", mapper.selectDecision(runId));
        body.put("kpis", mapper.selectKpis(runId));
        body.put("candidates", mapper.selectCandidates(runId));
        body.put("adjustments", mapper.selectAdjustments(runId));
        body.put("conflicts", mapper.selectConflicts(runId));
        body.put("scenarios", mapper.selectScenarioResults(runId));
        return body;
    }

    @Override
    public Map<String, Object> rolling(Long deptId, String runId)
    {
        requireSucceeded(deptId, runId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("events", mapper.selectRollingEvents(runId));
        annotateRollingHold(body);
        return body;
    }

    @Override
    public Map<String, Object> robustness(Long deptId, String runId)
    {
        requireSucceeded(deptId, runId);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("auditSummary", mapper.selectAuditSummary(runId));
        body.put("decision", mapper.selectDecision(runId));
        body.put("artifacts", mapper.selectArtifactMeta(runId));
        return body;
    }

    @Override
    public List<Map<String, Object>> artifacts(Long deptId, String runId)
    {
        requireRun(deptId, runId);
        return mapper.selectArtifactMeta(runId);
    }

    @Override
    public Map<String, Object> downloadMeta(Long deptId, String runId, String relativePath)
    {
        EnergyAccessGuard.requireRelativePath(relativePath);
        requireRun(deptId, runId);
        Map<String, Object> artifact = mapper.selectArtifact(runId, relativePath);
        if (artifact == null)
        {
            throw new ServiceException("not found", HttpStatus.NOT_FOUND);
        }
        return artifact;
    }

    @Override
    public InputStream downloadStream(Long deptId, String runId, String relativePath)
    {
        Map<String, Object> artifact = downloadMeta(deptId, runId, relativePath);
        Object content = artifact.get("content");
        if (!(content instanceof byte[] bytes))
        {
            throw new ServiceException("工件内容不可读", HttpStatus.NOT_FOUND);
        }
        return new ByteArrayInputStream(bytes);
    }

    @Override
    public Path resolveUploadRoot()
    {
        return Path.of(properties.getUploadDir()).toAbsolutePath().normalize();
    }

    private static void requireVersionTopic(String projectCode, String versionCode, String topic)
    {
        if (projectCode == null || projectCode.isBlank() || versionCode == null || versionCode.isBlank())
        {
            throw new ServiceException("请选择数据版本", HttpStatus.BAD_REQUEST);
        }
        if (topic == null || topic.isBlank())
        {
            throw new ServiceException("请选择数据主题", HttpStatus.BAD_REQUEST);
        }
    }

    private void requireProjectVisible(Long deptId, String projectCode)
    {
        if (deptId == null)
        {
            return;
        }
        EnergyAccessGuard.requireBound(mapper.countDeptProject(deptId, projectCode) > 0);
    }

    private Map<String, Object> requireRun(Long deptId, String runId)
    {
        Map<String, Object> run = mapper.selectRun(runId);
        if (run == null)
        {
            throw new ServiceException("not found", HttpStatus.NOT_FOUND);
        }
        String projectCode = String.valueOf(run.get("projectCode"));
        requireProjectVisible(deptId, projectCode);
        return run;
    }

    private Map<String, Object> requireSucceeded(Long deptId, String runId)
    {
        Map<String, Object> run = requireRun(deptId, runId);
        if (!"succeeded".equals(String.valueOf(run.get("status"))))
        {
            throw new ServiceException("只有成功任务可以读取结果", HttpStatus.BAD_REQUEST);
        }
        return run;
    }

    public static void annotateRollingHold(Map<String, Object> body)
    {
        List<?> events = (List<?>) body.get("events");
        boolean withhold = false;
        if (events != null)
        {
            for (Object item : events)
            {
                if (item instanceof Map<?, ?> row && "withheld_infeasible".equals(String.valueOf(row.get("commitStatus"))))
                {
                    withhold = true;
                    break;
                }
            }
        }
        body.put("dispatchAllowed", !withhold);
        if (withhold)
        {
            body.put("holdReason", "withheld_infeasible");
        }
    }

    public static Map<String, Object> parseJsonMap(Object raw)
    {
        if (raw == null)
        {
            return new LinkedHashMap<>();
        }
        if (raw instanceof Map<?, ?> map)
        {
            JSONObject object = new JSONObject();
            object.putAll((Map<String, ?>) map);
            return object;
        }
        return JSON.parseObject(String.valueOf(raw));
    }
}
