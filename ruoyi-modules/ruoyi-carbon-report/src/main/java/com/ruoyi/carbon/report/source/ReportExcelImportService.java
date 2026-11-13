package com.ruoyi.carbon.report.source;

import java.io.InputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.carbon.report.mapper.ReportActivityMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptProfileMapper;
import com.ruoyi.carbon.report.mapper.ReportEquipmentMapper;
import com.ruoyi.carbon.report.mapper.ReportMonitoringDeviceMapper;
import com.ruoyi.carbon.report.mapper.ReportWorkloadMapper;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

@Service
public class ReportExcelImportService
{
    @Autowired
    private ReportEquipmentMapper equipmentMapper;

    @Autowired
    private ReportMonitoringDeviceMapper monitoringMapper;

    @Autowired
    private ReportWorkloadMapper workloadMapper;

    @Autowired
    private ReportActivityMapper activityMapper;

    @Autowired
    private ReportDeptProfileMapper profileMapper;

    public String apply(ReportTask task, ReportExcelType type, boolean overwrite, InputStream in, String username)
    {
        List<java.util.Map<String, String>> raw = ReportExcelParser.parse(in, type);
        switch (type)
        {
            case equipment:
                importEquipment(task, raw, overwrite, username);
                return "assets";
            case monitoring:
                importMonitoring(task, raw, overwrite, username);
                return "assets";
            case workload:
                importWorkload(task, raw, overwrite, username);
                return "activity";
            case heat:
                importHeat(task, raw, overwrite, username);
                return "activity";
            default:
                throw new ServiceException("未知导入类型", HttpStatus.BAD_REQUEST);
        }
    }

    private void importEquipment(ReportTask task, List<java.util.Map<String, String>> raw, boolean overwrite,
            String username)
    {
        List<ReportEquipment> excel = ReportExcelParser.toEquipment(raw);
        requireRows(excel);
        List<ReportEquipment> merged = ReportExcelMerger.mergeEquipment(currentEquipment(task), excel, overwrite);
        for (int i = 0; i < merged.size(); i++) ReportExcelParser.validateEquipment(merged.get(i), i + 1);
        equipmentMapper.deleteByReport(task.getId(), task.getDeptId());
        int order = 0;
        for (ReportEquipment row : merged)
        {
            stamp(row, task, username, order++);
            if (row.getDataOrigin() == null)
            {
                row.setDataOrigin(overwrite ? "IMPORT" : "MANUAL");
            }
            equipmentMapper.insert(row);
        }
    }

    private void importMonitoring(ReportTask task, List<java.util.Map<String, String>> raw, boolean overwrite,
            String username)
    {
        List<ReportMonitoringDevice> excel = ReportExcelParser.toMonitoring(raw);
        ReportMonitoringRules.validateLengths(excel);
        requireRows(excel);
        List<ReportMonitoringDevice> merged = ReportExcelMerger.mergeMonitoring(currentMonitoring(task), excel,
                overwrite);
        ReportMonitoringRules.validateLengths(merged);
        monitoringMapper.deleteByReport(task.getId(), task.getDeptId());
        int order = 0;
        for (ReportMonitoringDevice row : merged)
        {
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setSortOrder(order++);
            row.setCreateBy(username);
            row.setUpdateBy(username);
            if (row.getDataOrigin() == null)
            {
                row.setDataOrigin(overwrite ? "IMPORT" : "AUTO");
            }
            monitoringMapper.insert(row);
        }
    }

    private void importWorkload(ReportTask task, List<java.util.Map<String, String>> raw, boolean overwrite,
            String username)
    {
        List<ReportWorkload> excel = ReportExcelParser.toWorkload(raw);
        requireRows(excel);
        List<ReportWorkload> merged = ReportExcelMerger.mergeWorkload(currentWorkload(task), excel, overwrite);
        ReportExcelParser.requireUniqueKeys(merged.stream().map(ReportWorkload::getName).collect(Collectors.toList()), "工作量指标，请先整理重复行：");
        for (int i = 0; i < merged.size(); i++) ReportExcelParser.validateWorkload(merged.get(i), i + 1);
        workloadMapper.deleteByReport(task.getId(), task.getDeptId());
        int order = 0;
        for (ReportWorkload row : merged)
        {
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setSortOrder(order++);
            row.setCreateBy(username);
            row.setUpdateBy(username);
            if (row.getDataOrigin() == null)
            {
                row.setDataOrigin(overwrite ? "IMPORT" : "MANUAL");
            }
            workloadMapper.insert(row);
        }
    }

    private void importHeat(ReportTask task, List<java.util.Map<String, String>> raw, boolean overwrite, String username)
    {
        List<ReportActivityRow> excel = ReportExcelParser.toHeat(raw);
        ReportExcelParser.requireUniqueKeys(excel.stream().map(ReportActivityRow::getSite).collect(Collectors.toList()),
                "热力站点");
        requireRows(excel);
        List<ReportActivityRow> current = activityMapper.selectHeat(task.getId(), task.getDeptId());
        List<ReportActivityRow> merged = ReportExcelMerger.mergeHeat(current, excel, overwrite);
        for (ReportActivityRow row : merged)
        {
            row.setDeptId(task.getDeptId());
            row.setReportId(task.getId());
            row.setUpdateBy(username);
            if (row.getId() != null)
            {
                activityMapper.updateHeatArea(row);
                continue;
            }
            row.setCreateBy(username);
            row.setKind("heat");
            row.setUnit("GJ");
            row.setNormalizedUnit("GJ");
            if (row.getDataOrigin() == null)
            {
                row.setDataOrigin("IMPORT");
            }
            activityMapper.insertHeat(row);
        }
    }

    List<ReportEquipment> currentEquipment(ReportTask task)
    {
        List<ReportEquipment> saved = equipmentMapper.selectByReport(task.getId(), task.getDeptId());
        if (saved != null && !saved.isEmpty())
        {
            return saved;
        }
        ReportDeptProfile profile = profileMapper.selectByDeptId(task.getDeptId());
        if (profile == null || blank(profile.getDefaultEquipmentJson()))
        {
            return new ArrayList<>();
        }
        return fromEquipmentJson(task, profile.getDefaultEquipmentJson());
    }

    List<ReportMonitoringDevice> currentMonitoring(ReportTask task)
    {
        List<ReportMonitoringDevice> saved = monitoringMapper.selectByReport(task.getId(), task.getDeptId());
        if (saved != null && !saved.isEmpty())
        {
            return saved;
        }
        return suggestedMonitoring(task);
    }

    List<ReportWorkload> currentWorkload(ReportTask task)
    {
        List<ReportWorkload> saved = workloadMapper.selectByReport(task.getId(), task.getDeptId());
        if (saved != null && !saved.isEmpty())
        {
            return saved;
        }
        ReportDeptProfile profile = profileMapper.selectByDeptId(task.getDeptId());
        if (profile == null || blank(profile.getDefaultWorkloadJson()))
        {
            return new ArrayList<>();
        }
        return fromWorkloadJson(profile.getDefaultWorkloadJson());
    }

    List<ReportMonitoringDevice> suggestedMonitoring(ReportTask task)
    {
        List<ReportMonitoringDevice> rows = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        for (ReportActivityRow item : activityMapper.selectFuels(task.getId(), task.getDeptId()))
        {
            addSuggested(rows, seen, first(item.getFacility(), item.getSourceName()), item.getSourceTable());
        }
        for (ReportActivityRow item : activityMapper.selectElectricity(task.getId(), task.getDeptId()))
        {
            addSuggested(rows, seen, first(item.getSourceName(), item.getFacility()), item.getSourceTable());
        }
        for (ReportActivityRow item : activityMapper.selectHeat(task.getId(), task.getDeptId()))
        {
            addSuggested(rows, seen, first(item.getSite(), item.getSourceName(), item.getFacility()),
                    item.getSourceTable());
        }
        return rows;
    }

    static List<ReportEquipment> fromEquipmentJson(ReportTask task, String json)
    {
        JSONArray items = parseArray(json);
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
            String name = text(item.getString("name"));
            if (name == null)
            {
                continue;
            }
            ReportEquipment row = new ReportEquipment();
            row.setName(name);
            row.setCategory(nvl(item.getString("category")));
            Object qty = item.get("quantity");
            row.setQuantity(qty == null || "".equals(qty) ? null : new BigDecimal(String.valueOf(qty)));
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
            rows.add(row);
        }
        return rows;
    }

    static List<ReportWorkload> fromWorkloadJson(String json)
    {
        JSONArray items = parseArray(json);
        List<ReportWorkload> rows = new ArrayList<>();
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
            String name = text(item.getString("name"));
            if (name == null)
            {
                continue;
            }
            ReportWorkload row = new ReportWorkload();
            row.setName(name);
            Object qty = item.get("quantity");
            row.setQuantity(qty == null || "".equals(qty) ? null : new BigDecimal(String.valueOf(qty)));
            row.setUnit(nvl(item.getString("unit")));
            row.setDataOrigin("MANUAL");
            rows.add(row);
        }
        return rows;
    }

    private static JSONArray parseArray(String json)
    {
        if (json == null || json.isBlank())
        {
            return null;
        }
        String trimmed = json.trim();
        if (trimmed.startsWith("["))
        {
            return JSON.parseArray(trimmed);
        }
        JSONObject obj = JSON.parseObject(trimmed);
        if (obj == null)
        {
            return null;
        }
        if (obj.getJSONArray("equipment") != null)
        {
            return obj.getJSONArray("equipment");
        }
        return obj.getJSONArray("workload");
    }

    private static void addSuggested(List<ReportMonitoringDevice> rows, Set<String> seen, String name, String sourceTable)
    {
        String key = ReportExcelMerger.normKey(name);
        if (key.isEmpty() || !seen.add(key))
        {
            return;
        }
        ReportMonitoringDevice row = new ReportMonitoringDevice();
        row.setName(name.trim());
        row.setModel("");
        row.setAccuracy("");
        row.setMeasurementRange("");
        row.setLocation("");
        row.setCalibrationFrequency("");
        row.setSourceTable(sourceTable == null ? "" : sourceTable);
        row.setDataOrigin("AUTO");
        rows.add(row);
    }

    private static String first(String... values)
    {
        if (values == null)
        {
            return "";
        }
        for (String value : values)
        {
            if (value != null && !value.isBlank())
            {
                return value;
            }
        }
        return "";
    }

    private static void stamp(ReportEquipment row, ReportTask task, String username, int order)
    {
        row.setId(null);
        row.setDeptId(task.getDeptId());
        row.setReportId(task.getId());
        row.setSortOrder(order);
        row.setCreateBy(username);
        row.setUpdateBy(username);
        if (row.getSourceId() == null)
        {
            row.setSourceId("");
        }
    }

    private static void requireRows(List<?> rows)
    {
        if (rows == null || rows.isEmpty())
        {
            throw new ServiceException("没有可导入的行", HttpStatus.BAD_REQUEST);
        }
    }

    private static boolean blank(String value)
    {
        return value == null || value.isBlank();
    }

    private static String text(String value)
    {
        if (value == null)
        {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static String nvl(String value)
    {
        String text = text(value);
        return text == null ? "" : text;
    }
}
