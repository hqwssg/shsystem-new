package com.ruoyi.carbon.report.service.impl;

import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.ReportGenerationJob;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.carbon.report.domain.dto.CreateReportRequest;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.generation.ActivityProseSanitizer;
import com.ruoyi.carbon.report.generation.CarbonReportRendererProperties;
import com.ruoyi.carbon.report.generation.DiskArtifactStore;
import com.ruoyi.carbon.report.generation.ReportImageSlots;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportActivityMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptSubjectMapper;
import com.ruoyi.carbon.report.mapper.ReportEquipmentMapper;
import com.ruoyi.carbon.report.mapper.ReportFileMapper;
import com.ruoyi.carbon.report.mapper.ReportGenerationJobMapper;
import com.ruoyi.carbon.report.mapper.ReportMonitoringDeviceMapper;
import com.ruoyi.carbon.report.mapper.ReportTaskMapper;
import com.ruoyi.carbon.report.mapper.ReportWorkloadMapper;
import com.ruoyi.carbon.report.service.IReportTaskService;
import com.ruoyi.carbon.report.service.ReportAccessGuard;
import com.ruoyi.carbon.report.source.ReportExcelImportService;
import com.ruoyi.carbon.report.source.ReportExcelParser;
import com.ruoyi.carbon.report.source.ReportExcelType;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.datascope.annotation.DataScope;

@Service
public class ReportTaskServiceImpl implements IReportTaskService
{
    @Autowired
    private ReportTaskMapper reportTaskMapper;

    @Autowired
    private ReportDeptSubjectMapper reportDeptSubjectMapper;

    @Autowired
    private ReportActivityMapper reportActivityMapper;

    @Autowired
    private ReportEquipmentMapper reportEquipmentMapper;

    @Autowired
    private ReportWorkloadMapper reportWorkloadMapper;

    @Autowired
    private ReportMonitoringDeviceMapper reportMonitoringDeviceMapper;

    @Autowired
    private ReportFileMapper reportFileMapper;

    @Autowired
    private ReportExcelImportService reportExcelImportService;

    @Autowired
    private CarbonReportRendererProperties rendererProperties;

    @Autowired
    private EmissionCalculationMapper emissionCalculationMapper;

    @Autowired
    private ReportGenerationJobMapper reportGenerationJobMapper;

    @Override
    @DataScope(deptAlias = "t", permission = "carbon:report:list")
    public List<ReportTask> list(ReportTask query)
    {
        List<ReportTask> rows = reportTaskMapper.selectList(query);
        for (ReportTask task : rows)
        {
            attachLatestArtifacts(task);
        }
        return rows;
    }

    @Override
    public ReportTask get(Long id, Long deptId)
    {
        return ReportAccessGuard.requireTask(reportTaskMapper.selectById(id), deptId);
    }

    @Override
    public ReportDraft getDraft(Long id, Long deptId)
    {
        ReportTask task = get(id, deptId);
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getFuels().addAll(reportActivityMapper.selectFuels(id, deptId));
        draft.getElectricity().addAll(reportActivityMapper.selectElectricity(id, deptId));
        draft.getHeat().addAll(reportActivityMapper.selectHeat(id, deptId));
        draft.getEquipment().addAll(reportEquipmentMapper.selectByReport(id, deptId));
        draft.getWorkload().addAll(reportWorkloadMapper.selectByReport(id, deptId));
        draft.getMonitoring().addAll(reportMonitoringDeviceMapper.selectByReport(id, deptId));
        draft.getImages().addAll(reportFileMapper.selectUploadsByReport(id, deptId));
        int filled = 0;
        for (ReportWorkload row : draft.getWorkload())
        {
            if (row.getQuantity() != null && row.getQuantity().compareTo(BigDecimal.ZERO) > 0)
            {
                filled++;
            }
        }
        draft.setWorkloadCount(filled);
        draft.setMissingWorkload(filled <= 0);
        if (needsPriorLookup(task))
        {
            try
            {
                String prior = lookupPriorYear(task);
                if (prior != null)
                {
                    task.setPriorYearJson(prior);
                }
                else if (isMonthTask(task))
                {
                    task.setPriorYearJson(null);
                }
            }
            catch (Exception ignored)
            {
                // 对比期核算或快照缺失时不挡草稿，校验步可手填。
            }
        }
        ReportGenerationJob latest = latestArtifacts(task.getId(), task.getDeptId());
        draft.setLatestJob(latest);
        attachLatestArtifacts(task, latest);
        return draft;
    }

    @Override
    public void markGenerated(Long id, Long deptId)
    {
        get(id, deptId);
        reportTaskMapper.markGenerated(id, deptId);
    }

    @Override
    public ReportTask create(CreateReportRequest request, Long deptId, String username)
    {
        ReportDeptSubject subject = reportDeptSubjectMapper.selectByDeptId(deptId);
        if (subject == null || !subject.isEnabled() || subject.getSubjectNodeId() == null)
        {
            throw new ServiceException("当前部门未配置可出报告的核算主体对照", HttpStatus.BAD_REQUEST);
        }
        if (request.getReportYear() == null)
        {
            throw new ServiceException("请选择报告年度", HttpStatus.BAD_REQUEST);
        }
        ReportTask task = new ReportTask();
        task.setDeptId(deptId);
        task.setTitle(request.getTitle() == null ? defaultTitle(request) : request.getTitle());
        task.setTemplateCode("suning");
        task.setPeriodType(request.getPeriodType() == null ? "YEAR" : request.getPeriodType());
        task.setReportYear(request.getReportYear());
        task.setReportMonth(request.getReportMonth());
        task.setPeriodStart(periodStart(request));
        task.setPeriodEnd(periodEnd(request));
        task.setSubjectNodeId(subject.getSubjectNodeId());
        task.setCalculationTemplateId(request.getCalculationTemplateId());
        task.setStatus("DRAFT");
        task.setCurrentStep("basic");
        task.setVersion(1);
        task.setCreateBy(username);
        task.setUpdateBy(username);
        reportTaskMapper.insert(task);
        return task;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ReportTask saveSection(Long id, Long deptId, String section, Integer version, String payloadJson, String username)
    {
        ReportTask task = get(id, deptId);
        ReportAccessGuard.requireVersion(task.getVersion(), version);
        switch (section)
        {
            case "basic":
                task.setMetadataJson(payloadJson);
                break;
            case "boundary":
                applyBoundaryPayload(task, payloadJson);
                break;
            case "assets":
                replaceEquipment(task, payloadJson, username);
                replaceMonitoring(task, payloadJson, username);
                break;
            case "workload":
                replaceWorkload(task, payloadJson, username);
                break;
            case "heat":
                updateHeatArea(task, payloadJson, username);
                break;
            case "narrative":
                task.setActivityProseJson(ActivityProseSanitizer.sanitize(payloadJson).toJSONString());
                break;
            case "prior_year":
                task.setPriorYearJson(applyPriorYearPayload(payloadJson));
                break;
            case "review":
                task.setLastValidationJson(payloadJson);
                break;
            default:
                throw new ServiceException("unknown section", HttpStatus.BAD_REQUEST);
        }
        task.setCurrentStep(section);
        task.setUpdateBy(username);
        int rows = reportTaskMapper.updateWithVersion(task);
        if (rows == 0)
        {
            throw new ServiceException("version conflict", HttpStatus.CONFLICT);
        }
        task.setVersion(task.getVersion() + 1);
        return task;
    }

    @Override
    public byte[] excelTemplate(String type)
    {
        return ReportExcelParser.templateBytes(ReportExcelType.from(type));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ReportTask importExcel(Long id, Long deptId, String type, String mode, Integer version, String originalName,
            InputStream in, String username)
    {
        ReportTask task = get(id, deptId);
        ReportAccessGuard.requireVersion(task.getVersion(), version);
        String filename = originalName == null ? "" : originalName.toLowerCase();
        if (!filename.endsWith(".xlsx") && !filename.endsWith(".xls"))
        {
            throw new ServiceException("只支持 xls 或 xlsx", HttpStatus.BAD_REQUEST);
        }
        boolean overwrite = parseOverwrite(mode);
        String step = reportExcelImportService.apply(task, ReportExcelType.from(type), overwrite, in, username);
        task.setCurrentStep(step);
        task.setUpdateBy(username);
        int rows = reportTaskMapper.updateWithVersion(task);
        if (rows == 0)
        {
            throw new ServiceException("version conflict", HttpStatus.CONFLICT);
        }
        task.setVersion(task.getVersion() + 1);
        return task;
    }

    private static boolean parseOverwrite(String mode)
    {
        if (mode == null || mode.isBlank() || "append".equalsIgnoreCase(mode))
        {
            return false;
        }
        if ("overwrite".equalsIgnoreCase(mode))
        {
            return true;
        }
        throw new ServiceException("导入方式只能是追加或覆盖", HttpStatus.BAD_REQUEST);
    }

    @Override
    public void remove(Long id, Long deptId, String username)
    {
        ReportTask task = get(id, deptId);
        task.setUpdateBy(username);
        if (reportTaskMapper.markDeleted(task) == 0)
        {
            throw new ServiceException("not found", HttpStatus.NOT_FOUND);
        }
    }

    @Override
    public ReportFile uploadImage(Long id, Long deptId, String role, String originalName, String contentType,
            long size, InputStream in, String username)
    {
        if (!ReportImageSlots.isRole(role))
        {
            throw new ServiceException("不支持的图片角色", HttpStatus.BAD_REQUEST);
        }
        ReportTask task = get(id, deptId);
        String mime = contentType == null ? "" : contentType.toLowerCase();
        if (!mime.startsWith("image/png") && !mime.startsWith("image/jpeg") && !mime.startsWith("image/jpg"))
        {
            String name = originalName == null ? "" : originalName.toLowerCase();
            if (name.endsWith(".png"))
            {
                mime = "image/png";
            }
            else if (name.endsWith(".jpg") || name.endsWith(".jpeg"))
            {
                mime = "image/jpeg";
            }
        }
        if (!mime.startsWith("image/png") && !mime.startsWith("image/jpeg") && !mime.startsWith("image/jpg"))
        {
            throw new ServiceException("只支持 PNG 或 JPEG 图片", HttpStatus.BAD_REQUEST);
        }
        if (size <= 0 || size > 5L * 1024 * 1024)
        {
            throw new ServiceException("图片需小于 5MB", HttpStatus.BAD_REQUEST);
        }
        String ext = ReportImageSlots.extensionOf(originalName, mime);
        DiskArtifactStore store = new DiskArtifactStore(rendererProperties.artifactDirPath());
        Path target = store.prepareUpload(deptId, id, role, ext);
        try
        {
            Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
        }
        catch (Exception ex)
        {
            throw new ServiceException("保存图片失败: " + ex.getMessage());
        }
        reportFileMapper.deleteUploadByReportRole(id, deptId, role);
        ReportFile file = new ReportFile();
        file.setDeptId(deptId);
        file.setReportId(id);
        file.setKind("upload");
        file.setRole(role);
        file.setObjectKey(store.relativeKey(target));
        file.setOriginalName(originalName == null ? role + "." + ext : originalName);
        file.setMimeType(mime.startsWith("image/png") ? "image/png" : "image/jpeg");
        try
        {
            file.setSizeBytes(Files.size(target));
        }
        catch (Exception ex)
        {
            file.setSizeBytes(size);
        }
        file.setSha256("");
        file.setSnapshotSha256("");
        file.setCreateBy(username);
        file.setUpdateBy(username);
        reportFileMapper.insert(file);
        return file;
    }

    @Override
    public void resetImage(Long id, Long deptId, String role)
    {
        if (!ReportImageSlots.isRole(role))
        {
            throw new ServiceException("不支持的图片角色", HttpStatus.BAD_REQUEST);
        }
        get(id, deptId);
        reportFileMapper.deleteUploadByReportRole(id, deptId, role);
    }

    @Override
    public Path defaultImagePath(String role)
    {
        Path path = ReportImageSlots.defaultAssetPath(rendererProperties.moduleRootPath(), role);
        if (!Files.isRegularFile(path))
        {
            throw new ServiceException("默认图片不存在", HttpStatus.NOT_FOUND);
        }
        return path;
    }

    private void replaceEquipment(ReportTask task, String payloadJson, String username)
    {
        reportEquipmentMapper.deleteByReport(task.getId(), task.getDeptId());
        for (ReportEquipment row : parseEquipmentPayload(task, payloadJson, username))
        {
            reportEquipmentMapper.insert(row);
        }
    }

    static List<ReportEquipment> parseEquipmentPayload(ReportTask task, String payloadJson, String username)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        JSONArray items = raw.getJSONArray("equipment");
        List<ReportEquipment> rows = new ArrayList<>();
        if (items == null)
        {
            return rows;
        }
        for (int i = 0; i < items.size(); i++)
        {
            JSONObject item = items.getJSONObject(i);
            if (item == null)
            {
                continue;
            }
            ReportEquipment row = new ReportEquipment();
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setName(nvl(item.getString("name")));
            row.setCategory(nvl(item.getString("category")));
            row.setQuantity(toDecimal(item.get("quantity")));
            row.setUnit(nvl(item.getString("unit")));
            row.setModel(nvl(item.getString("model")));
            String energy = item.getString("energyType");
            if (energy == null || energy.isBlank())
            {
                energy = item.getString("energy_type");
            }
            row.setEnergyType(nvl(energy));
            row.setRemark(nvl(item.getString("remark")));
            row.setDataOrigin("MANUAL");
            row.setSourceId("");
            row.setSortOrder(i);
            row.setCreateBy(username);
            row.setUpdateBy(username);
            rows.add(row);
        }
        return rows;
    }

    private static BigDecimal toDecimal(Object value)
    {
        if (value == null || "".equals(value))
        {
            return BigDecimal.ZERO;
        }
        return new BigDecimal(String.valueOf(value));
    }

    private static BigDecimal toDecimalOrNull(Object value)
    {
        if (value == null || "".equals(value))
        {
            return null;
        }
        return new BigDecimal(String.valueOf(value));
    }

    private void replaceMonitoring(ReportTask task, String payloadJson, String username)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        if (!raw.containsKey("monitoring"))
        {
            return;
        }
        reportMonitoringDeviceMapper.deleteByReport(task.getId(), task.getDeptId());
        for (ReportMonitoringDevice row : parseMonitoringPayload(task, payloadJson, username))
        {
            reportMonitoringDeviceMapper.insert(row);
        }
    }

    static List<ReportMonitoringDevice> parseMonitoringPayload(ReportTask task, String payloadJson, String username)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        JSONArray items = raw.getJSONArray("monitoring");
        List<ReportMonitoringDevice> rows = new ArrayList<>();
        if (items == null)
        {
            return rows;
        }
        for (int i = 0; i < items.size(); i++)
        {
            JSONObject item = items.getJSONObject(i);
            if (item == null)
            {
                continue;
            }
            String name = nvl(item.getString("name"));
            if (name.isBlank())
            {
                continue;
            }
            ReportMonitoringDevice row = new ReportMonitoringDevice();
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setName(name);
            row.setModel(nvl(item.getString("model")));
            row.setAccuracy(nvl(item.getString("accuracy")));
            row.setLocation(nvl(item.getString("location")));
            String freq = item.getString("calibrationFrequency");
            if (freq == null || freq.isBlank())
            {
                freq = item.getString("calibration_frequency");
            }
            row.setCalibrationFrequency(nvl(freq));
            String range = item.getString("measurementRange");
            if (range == null || range.isBlank())
            {
                range = item.getString("measurement_range");
            }
            row.setMeasurementRange(nvl(range));
            row.setDataOrigin("MANUAL");
            row.setSourceTable(nvl(item.getString("sourceTable")));
            row.setSourceId(nvl(item.getString("sourceId")));
            row.setSortOrder(i);
            row.setCreateBy(username);
            row.setUpdateBy(username);
            rows.add(row);
        }
        return rows;
    }

    private void replaceWorkload(ReportTask task, String payloadJson, String username)
    {
        reportWorkloadMapper.deleteByReport(task.getId(), task.getDeptId());
        for (ReportWorkload row : parseWorkloadPayload(task, payloadJson, username))
        {
            reportWorkloadMapper.insert(row);
        }
    }

    private void updateHeatArea(ReportTask task, String payloadJson, String username)
    {
        for (ReportActivityRow row : parseHeatAreaPayload(task, payloadJson, username))
        {
            reportActivityMapper.updateHeatArea(row);
        }
    }

    static List<ReportActivityRow> parseHeatAreaPayload(ReportTask task, String payloadJson, String username)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        JSONArray items = raw.getJSONArray("heat");
        List<ReportActivityRow> rows = new ArrayList<>();
        if (items == null)
        {
            return rows;
        }
        for (int i = 0; i < items.size(); i++)
        {
            JSONObject item = items.getJSONObject(i);
            if (item == null)
            {
                continue;
            }
            Long id = item.getLong("id");
            if (id == null)
            {
                continue;
            }
            ReportActivityRow row = new ReportActivityRow();
            row.setId(id);
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setHeatingAreaM2(firstDecimal(item, "heatingAreaM2", "heating_area_m2"));
            row.setHeatCoefficient(firstDecimal(item, "heatCoefficient", "heat_coefficient"));
            row.setUpdateBy(username);
            rows.add(row);
        }
        return rows;
    }

    private static BigDecimal firstDecimal(JSONObject item, String camel, String snake)
    {
        if (item.containsKey(camel))
        {
            return toDecimalOrNull(item.get(camel));
        }
        if (item.containsKey(snake))
        {
            return toDecimalOrNull(item.get(snake));
        }
        return null;
    }

    static List<ReportWorkload> parseWorkloadPayload(ReportTask task, String payloadJson, String username)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        JSONArray items = raw.getJSONArray("workload");
        List<ReportWorkload> rows = new ArrayList<>();
        if (items == null)
        {
            return rows;
        }
        int order = 0;
        for (int i = 0; i < items.size(); i++)
        {
            JSONObject item = items.getJSONObject(i);
            if (item == null)
            {
                continue;
            }
            BigDecimal quantity = toDecimalOrNull(item.get("quantity"));
            if (quantity == null || quantity.compareTo(BigDecimal.ZERO) <= 0)
            {
                continue;
            }
            String name = nvl(item.getString("name"));
            if (name.isBlank())
            {
                continue;
            }
            ReportWorkload row = new ReportWorkload();
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setName(name);
            row.setQuantity(quantity);
            row.setUnit(nvl(item.getString("unit")));
            row.setDataOrigin("MANUAL");
            row.setSortOrder(order++);
            row.setCreateBy(username);
            row.setUpdateBy(username);
            rows.add(row);
        }
        return rows;
    }

    static boolean isMonthTask(ReportTask task)
    {
        return task != null && "MONTH".equalsIgnoreCase(task.getPeriodType());
    }

    static boolean isMonthlyComparisonJson(String json)
    {
        if (json == null || json.isBlank())
        {
            return false;
        }
        try
        {
            JSONObject raw = JSON.parseObject(json);
            return raw != null && (raw.getJSONObject("yoy") != null || raw.getJSONObject("mom") != null);
        }
        catch (Exception ex)
        {
            return false;
        }
    }

    static boolean needsPriorLookup(ReportTask task)
    {
        String json = task == null ? null : task.getPriorYearJson();
        if (json == null || json.isBlank())
        {
            return true;
        }
        return isMonthTask(task) && !isMonthlyComparisonJson(json);
    }

    static int[] previousMonth(int year, int month)
    {
        if (month <= 1)
        {
            return new int[] { year - 1, 12 };
        }
        return new int[] { year, month - 1 };
    }

    static Date[] monthRange(int year, int month)
    {
        Calendar start = Calendar.getInstance();
        start.clear();
        start.set(year, month - 1, 1);
        Calendar end = (Calendar) start.clone();
        end.add(Calendar.MONTH, 1);
        end.add(Calendar.DATE, -1);
        return new Date[] { start.getTime(), end.getTime() };
    }

    static Date startOfDay(Date date)
    {
        Calendar calendar = Calendar.getInstance();
        calendar.setTime(date);
        calendar.set(Calendar.HOUR_OF_DAY, 0);
        calendar.set(Calendar.MINUTE, 0);
        calendar.set(Calendar.SECOND, 0);
        calendar.set(Calendar.MILLISECOND, 0);
        return calendar.getTime();
    }

    static boolean cycleContainedIn(Date cycleStart, Date cycleEnd, Date periodStart, Date periodEnd)
    {
        if (cycleStart == null || cycleEnd == null || periodStart == null || periodEnd == null)
        {
            return false;
        }
        return !startOfDay(cycleStart).before(startOfDay(periodStart))
                && !startOfDay(cycleEnd).after(startOfDay(periodEnd));
    }

    static CalculationCandidate firstContained(List<CalculationCandidate> candidates, Date periodStart, Date periodEnd)
    {
        if (candidates == null)
        {
            return null;
        }
        for (CalculationCandidate candidate : candidates)
        {
            if (candidate != null && cycleContainedIn(candidate.getCycleStart(), candidate.getCycleEnd(), periodStart, periodEnd))
            {
                return candidate;
            }
        }
        return null;
    }

    static String applyPriorYearPayload(String payloadJson)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        if (raw.get("yoy") != null || raw.get("mom") != null)
        {
            JSONObject out = new JSONObject();
            JSONObject yoy = sanitizePeriodPayload(raw.getJSONObject("yoy"));
            JSONObject mom = sanitizePeriodPayload(raw.getJSONObject("mom"));
            if (yoy != null)
            {
                out.put("yoy", yoy);
            }
            if (mom != null)
            {
                out.put("mom", mom);
            }
            return out.isEmpty() ? null : out.toJSONString();
        }
        JSONObject flat = sanitizePeriodPayload(raw);
        return flat == null ? null : flat.toJSONString();
    }

    static JSONObject sanitizePeriodPayload(JSONObject raw)
    {
        if (raw == null)
        {
            return null;
        }
        JSONObject out = new JSONObject();
        Integer year = raw.getInteger("report_year");
        Integer month = raw.getInteger("report_month");
        if (year != null)
        {
            out.put("report_year", year);
        }
        if (month != null)
        {
            out.put("report_month", month);
        }
        putDecimal(out, raw, "total_emissions_tco2");
        putDecimal(out, raw, "fuel_combustion_tco2");
        putDecimal(out, raw, "electricity_emissions_tco2");
        putDecimal(out, raw, "heat_emissions_tco2");
        if (out.get("total_emissions_tco2") == null)
        {
            return null;
        }
        return out;
    }

    private static void putDecimal(JSONObject out, JSONObject raw, String key)
    {
        Object value = raw.get(key);
        if (value == null || "".equals(value))
        {
            return;
        }
        out.put(key, new BigDecimal(String.valueOf(value)));
    }

    String lookupPriorYear(ReportTask task)
    {
        if (isMonthTask(task))
        {
            return lookupMonthlyComparisons(task);
        }
        if (task.getReportYear() == null || task.getDeptId() == null)
        {
            return null;
        }
        int prevYear = task.getReportYear() - 1;
        if (reportGenerationJobMapper != null)
        {
            String snapshot = reportGenerationJobMapper.selectLatestSucceededSnapshot(task.getDeptId(), prevYear);
            String fromSnapshot = extractPriorFromSnapshot(snapshot, prevYear);
            if (fromSnapshot != null)
            {
                return fromSnapshot;
            }
        }
        Calendar start = Calendar.getInstance();
        start.clear();
        start.set(prevYear, Calendar.JANUARY, 1);
        Calendar end = Calendar.getInstance();
        end.clear();
        end.set(prevYear, Calendar.DECEMBER, 31);
        JSONObject prior = totalsFromCalculation(task, start.getTime(), end.getTime(), false);
        if (prior == null)
        {
            return null;
        }
        prior.put("report_year", prevYear);
        return prior.toJSONString();
    }

    String lookupMonthlyComparisons(ReportTask task)
    {
        if (task.getReportYear() == null || task.getReportMonth() == null || task.getDeptId() == null)
        {
            return null;
        }
        JSONObject out = new JSONObject();
        JSONObject yoy = lookupMonthFromCalculation(task, task.getReportYear() - 1, task.getReportMonth());
        int[] prev = previousMonth(task.getReportYear(), task.getReportMonth());
        JSONObject mom = lookupMonthFromCalculation(task, prev[0], prev[1]);
        if (yoy != null)
        {
            out.put("yoy", yoy);
        }
        if (mom != null)
        {
            out.put("mom", mom);
        }
        return out.isEmpty() ? null : out.toJSONString();
    }

    JSONObject lookupMonthFromCalculation(ReportTask task, int year, int month)
    {
        Date[] range = monthRange(year, month);
        JSONObject prior = totalsFromCalculation(task, range[0], range[1], true);
        if (prior == null)
        {
            return null;
        }
        prior.put("report_year", year);
        prior.put("report_month", month);
        return prior;
    }

    JSONObject totalsFromCalculation(ReportTask task, Date periodStart, Date periodEnd, boolean requireContained)
    {
        if (emissionCalculationMapper == null || reportDeptSubjectMapper == null)
        {
            return null;
        }
        ReportDeptSubject subject = reportDeptSubjectMapper.selectByDeptId(task.getDeptId());
        if (subject == null || subject.getSubjectNodeId() == null || subject.getEnergyAllocation() == null)
        {
            return null;
        }
        List<CalculationCandidate> candidates = emissionCalculationMapper.selectCandidates(
                subject.getSubjectNodeId(), periodStart, periodEnd);
        CalculationCandidate chosen = requireContained
                ? firstContained(candidates, periodStart, periodEnd)
                : (candidates == null || candidates.isEmpty() ? null : candidates.get(0));
        if (chosen == null)
        {
            return null;
        }
        List<CalculationNodeDataRow> rows = emissionCalculationMapper.selectNodeData(
                chosen.getId(), subject.getEnergyAllocation());
        return totalsFromRows(rows);
    }

    static JSONObject totalsFromRows(List<CalculationNodeDataRow> rows)
    {
        if (rows == null || rows.isEmpty())
        {
            return null;
        }
        BigDecimal fuel = BigDecimal.ZERO;
        BigDecimal electricity = BigDecimal.ZERO;
        BigDecimal heat = BigDecimal.ZERO;
        for (CalculationNodeDataRow row : rows)
        {
            BigDecimal value = row.getCarbonEmission() == null ? BigDecimal.ZERO : row.getCarbonEmission();
            String category = row.getEmissionCategory() == null ? "" : row.getEmissionCategory();
            if (category.contains("燃料"))
            {
                fuel = fuel.add(value);
            }
            else if (category.contains("电"))
            {
                electricity = electricity.add(value);
            }
            else if (category.contains("热"))
            {
                heat = heat.add(value);
            }
            else
            {
                fuel = fuel.add(value);
            }
        }
        JSONObject prior = new JSONObject();
        prior.put("fuel_combustion_tco2", fuel);
        prior.put("electricity_emissions_tco2", electricity);
        prior.put("heat_emissions_tco2", heat);
        prior.put("total_emissions_tco2", fuel.add(electricity).add(heat));
        return prior;
    }

    static String extractPriorFromSnapshot(String snapshotJson, int prevYear)
    {
        if (snapshotJson == null || snapshotJson.isBlank())
        {
            return null;
        }
        JSONObject snapshot;
        try
        {
            snapshot = JSON.parseObject(snapshotJson);
        }
        catch (Exception ex)
        {
            return null;
        }
        if (snapshot == null)
        {
            return null;
        }
        JSONObject chapter6 = snapshot.getJSONObject("chapter6");
        if (chapter6 != null)
        {
            JSONArray years = chapter6.getJSONArray("trend_years");
            if (years != null)
            {
                for (int i = 0; i < years.size(); i++)
                {
                    JSONObject row = years.getJSONObject(i);
                    if (row != null && prevYear == row.getIntValue("year"))
                    {
                        JSONObject prior = new JSONObject();
                        prior.put("report_year", prevYear);
                        copyIfPresent(prior, row, "total_emissions_tco2");
                        copyIfPresent(prior, row, "fuel_combustion_tco2");
                        copyIfPresent(prior, row, "electricity_emissions_tco2");
                        copyIfPresent(prior, row, "heat_emissions_tco2");
                        if (prior.get("total_emissions_tco2") != null)
                        {
                            return prior.toJSONString();
                        }
                    }
                }
            }
        }
        JSONObject nested = snapshot.getJSONObject("prior_year");
        if (nested != null && prevYear == nested.getIntValue("report_year")
                && nested.get("total_emissions_tco2") != null)
        {
            return applyPriorYearPayload(nested.toJSONString());
        }
        return null;
    }

    private static void copyIfPresent(JSONObject out, JSONObject raw, String key)
    {
        Object value = raw.get(key);
        if (value != null && !"".equals(value))
        {
            out.put(key, value);
        }
    }

    static void applyBoundaryPayload(ReportTask task, String payloadJson)
    {
        JSONObject raw = payloadJson == null || payloadJson.isBlank() ? new JSONObject() : JSON.parseObject(payloadJson);
        JSONObject boundary = new JSONObject();
        boundary.put("boundary_description", nvl(raw.getString("boundary_description")));
        boundary.put("accounting_method", nvl(raw.getString("accounting_method")));
        JSONArray sources = raw.getJSONArray("emission_sources");
        boundary.put("emission_sources", sources == null ? new JSONArray() : sources);
        JSONArray rows = raw.getJSONArray("emission_source_rows");
        boundary.put("emission_source_rows", rows == null ? new JSONArray() : rows);
        task.setOrganizationBoundaryJson(boundary.toJSONString());
        JSONObject notes = new JSONObject();
        notes.put("fuel_boundary_exclusion", nvl(raw.getString("fuel_boundary_exclusion")));
        task.setEmissionBoundaryNotesJson(notes.toJSONString());
    }

    private static String nvl(String value)
    {
        return value == null ? "" : value;
    }

    private static String defaultTitle(CreateReportRequest request)
    {
        if ("MONTH".equalsIgnoreCase(request.getPeriodType()))
        {
            return request.getReportYear() + "年" + request.getReportMonth() + "月温室气体排放报告";
        }
        return request.getReportYear() + "年度温室气体排放报告";
    }

    private static Date periodStart(CreateReportRequest request)
    {
        Calendar calendar = Calendar.getInstance();
        calendar.clear();
        if ("MONTH".equalsIgnoreCase(request.getPeriodType()) && request.getReportMonth() != null)
        {
            calendar.set(request.getReportYear(), request.getReportMonth() - 1, 1);
        }
        else
        {
            calendar.set(request.getReportYear(), Calendar.JANUARY, 1);
        }
        return calendar.getTime();
    }

    private static Date periodEnd(CreateReportRequest request)
    {
        Calendar calendar = Calendar.getInstance();
        calendar.clear();
        if ("MONTH".equalsIgnoreCase(request.getPeriodType()) && request.getReportMonth() != null)
        {
            calendar.set(request.getReportYear(), request.getReportMonth() - 1, 1);
            calendar.add(Calendar.MONTH, 1);
            calendar.add(Calendar.DATE, -1);
        }
        else
        {
            calendar.set(request.getReportYear(), Calendar.DECEMBER, 31);
        }
        return calendar.getTime();
    }

    private void attachLatestArtifacts(ReportTask task)
    {
        attachLatestArtifacts(task, latestArtifacts(task.getId(), task.getDeptId()));
    }

    private void attachLatestArtifacts(ReportTask task, ReportGenerationJob job)
    {
        if (task == null || job == null)
        {
            return;
        }
        task.setLatestDocxFileId(job.getDocxFileId());
        task.setLatestPdfFileId(job.getPdfFileId());
        if ("DRAFT".equals(task.getStatus()) && (job.getDocxFileId() != null || job.getPdfFileId() != null))
        {
            reportTaskMapper.markGenerated(task.getId(), task.getDeptId());
            task.setStatus("GENERATED");
        }
    }

    private ReportGenerationJob latestArtifacts(Long reportId, Long deptId)
    {
        ReportGenerationJob job = reportGenerationJobMapper.selectLatestSucceeded(reportId, deptId);
        if (job == null)
        {
            return null;
        }
        if (job.getDocxFileId() == null)
        {
            job.setDocxFileId(reportGenerationJobMapper.selectLatestDocxFileId(reportId, deptId));
        }
        if (job.getPdfFileId() == null)
        {
            job.setPdfFileId(reportGenerationJobMapper.selectLatestPdfFileId(reportId, deptId));
        }
        return job;
    }
}
