package com.ruoyi.carbon.report.source;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.springframework.beans.BeanUtils;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportWorkload;

/**
 * Merges Excel rows onto the currently displayed lookup set.
 * Overwrite replaces keyed rows for list types; heat keeps existing sites and never touches GJ.
 */
public final class ReportExcelMerger
{
    private ReportExcelMerger()
    {
    }

    public static List<ReportEquipment> mergeEquipment(List<ReportEquipment> current, List<ReportEquipment> excel,
            boolean overwrite)
    {
        if (overwrite)
        {
            return copyEquipment(excel);
        }
        List<ReportEquipment> rows = copyEquipment(current);
        rows.addAll(copyEquipment(excel));
        return rows;
    }

    public static List<ReportMonitoringDevice> mergeMonitoring(List<ReportMonitoringDevice> current,
            List<ReportMonitoringDevice> excel, boolean overwrite)
    {
        if (overwrite)
        {
            return copyMonitoring(excel);
        }
        List<ReportMonitoringDevice> merged = copyMonitoring(current);
        merged.addAll(copyMonitoring(excel));
        return merged;
    }

    public static List<ReportWorkload> mergeWorkload(List<ReportWorkload> current, List<ReportWorkload> excel,
            boolean overwrite)
    {
        List<ReportWorkload> rows = overwrite ? new ArrayList<>() : copyWorkload(current);
        if (excel == null) return rows;
        for (ReportWorkload incoming : excel) {
            List<ReportWorkload> matches = rows.stream().filter(r -> normKey(r.getName()).equals(normKey(incoming.getName()))).toList();
            if (matches.size() > 1) throw conflict(incoming.getName(), "匹配到多条指标，请先核对");
            if (matches.isEmpty()) { rows.add(copyWorkloadRow(incoming)); continue; }
            ReportWorkload existing = matches.get(0);
            if (!normKey(existing.getUnit()).isEmpty() && !normKey(incoming.getUnit()).isEmpty()
                    && !normKey(existing.getUnit()).equals(normKey(incoming.getUnit())))
                throw conflict(incoming.getName(), "单位不一致，不能合并");
            if (existing.getQuantity() == null || existing.getQuantity().signum() == 0) {
                existing.setQuantity(incoming.getQuantity());
                if (normKey(existing.getUnit()).isEmpty()) existing.setUnit(incoming.getUnit());
            } else if (incoming.getQuantity() == null || existing.getQuantity().compareTo(incoming.getQuantity()) != 0)
                throw conflict(incoming.getName(), "已有不同数量，请选择覆盖或在页面核对修改，不自动累加");
        }
        return rows;
    }

    public static List<ReportActivityRow> mergeHeat(List<ReportActivityRow> current, List<ReportActivityRow> excel,
            boolean overwrite)
    {
        List<ReportActivityRow> rows = new ArrayList<>();
        if (current != null) for (ReportActivityRow original : current) {
            ReportActivityRow copy = new ReportActivityRow(); BeanUtils.copyProperties(original, copy); rows.add(copy);
        }
        if (excel == null) return rows;
        for (ReportActivityRow incoming : excel) {
            List<ReportActivityRow> matches = rows.stream().filter(r -> normKey(r.getSite()).equals(normKey(incoming.getSite()))).toList();
            if (matches.size() > 1) throw conflict(incoming.getSite(), "匹配到多条热力记录，请在页面逐行核对，不按名称任意覆盖");
            if (matches.isEmpty()) { rows.add(newHeatSite(incoming)); continue; }
            ReportActivityRow existing = matches.get(0);
            if (incoming.getHeatingAreaM2() != null && (overwrite || existing.getHeatingAreaM2() == null)) existing.setHeatingAreaM2(incoming.getHeatingAreaM2());
            if (incoming.getHeatCoefficient() != null && (overwrite || existing.getHeatCoefficient() == null)) existing.setHeatCoefficient(incoming.getHeatCoefficient());
        }
        return rows;
    }

    private static ServiceException conflict(String name, String reason) {
        return new ServiceException("“" + name + "”" + reason, HttpStatus.BAD_REQUEST);
    }

    public static String normKey(String value)
    {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    private static ReportActivityRow newHeatSite(ReportActivityRow incoming)
    {
        ReportActivityRow created = new ReportActivityRow();
        created.setSite(incoming.getSite());
        created.setSourceName(incoming.getSite());
        created.setHeatingAreaM2(incoming.getHeatingAreaM2());
        created.setHeatCoefficient(incoming.getHeatCoefficient());
        created.setQuantity(null);
        created.setNormalizedValue(null);
        created.setNormalizedUnit("GJ");
        created.setDataOrigin("IMPORT");
        return created;
    }

    private static List<ReportEquipment> copyEquipment(List<ReportEquipment> rows)
    {
        List<ReportEquipment> copied = new ArrayList<>();
        if (rows == null)
        {
            return copied;
        }
        for (ReportEquipment row : rows)
        {
            copied.add(copyEquipmentRow(row));
        }
        return copied;
    }

    private static ReportEquipment copyEquipmentRow(ReportEquipment row)
    {
        ReportEquipment next = new ReportEquipment();
        next.setName(row.getName());
        next.setCategory(row.getCategory());
        next.setQuantity(row.getQuantity());
        next.setUnit(row.getUnit());
        next.setModel(row.getModel());
        next.setEnergyType(row.getEnergyType());
        next.setRemark(row.getRemark());
        next.setSourceId(row.getSourceId());
        next.setDataOrigin(row.getDataOrigin() == null ? "IMPORT" : row.getDataOrigin());
        return next;
    }

    private static List<ReportMonitoringDevice> copyMonitoring(List<ReportMonitoringDevice> rows)
    {
        List<ReportMonitoringDevice> copied = new ArrayList<>();
        if (rows == null)
        {
            return copied;
        }
        for (ReportMonitoringDevice row : rows)
        {
            copied.add(copyMonitoringRow(row));
        }
        return copied;
    }

    private static ReportMonitoringDevice copyMonitoringRow(ReportMonitoringDevice row)
    {
        ReportMonitoringDevice next = new ReportMonitoringDevice();
        next.setName(row.getName());
        next.setModel(row.getModel());
        next.setAccuracy(row.getAccuracy());
        next.setMeasurementRange(row.getMeasurementRange());
        next.setLocation(row.getLocation());
        next.setCalibrationFrequency(row.getCalibrationFrequency());
        next.setSourceTable(row.getSourceTable());
        next.setSourceId(row.getSourceId());
        next.setDataOrigin(row.getDataOrigin() == null ? "IMPORT" : row.getDataOrigin());
        return next;
    }

    private static List<ReportWorkload> copyWorkload(List<ReportWorkload> rows)
    {
        List<ReportWorkload> copied = new ArrayList<>();
        if (rows == null)
        {
            return copied;
        }
        for (ReportWorkload row : rows)
        {
            copied.add(copyWorkloadRow(row));
        }
        return copied;
    }

    private static ReportWorkload copyWorkloadRow(ReportWorkload row)
    {
        ReportWorkload next = new ReportWorkload();
        next.setName(row.getName());
        next.setQuantity(row.getQuantity());
        next.setUnit(row.getUnit());
        next.setDataOrigin(row.getDataOrigin() == null ? "IMPORT" : row.getDataOrigin());
        return next;
    }
}
