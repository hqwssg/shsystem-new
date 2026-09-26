package com.ruoyi.carbon.report.source;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
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
        return appendByKey(current, excel, ReportEquipment::getName, ReportExcelMerger::copyEquipmentRow);
    }

    public static List<ReportMonitoringDevice> mergeMonitoring(List<ReportMonitoringDevice> current,
            List<ReportMonitoringDevice> excel, boolean overwrite)
    {
        if (overwrite)
        {
            return copyMonitoring(excel);
        }
        return appendByKey(current, excel, ReportMonitoringDevice::getName, ReportExcelMerger::copyMonitoringRow);
    }

    public static List<ReportWorkload> mergeWorkload(List<ReportWorkload> current, List<ReportWorkload> excel,
            boolean overwrite)
    {
        if (overwrite)
        {
            return copyWorkload(excel);
        }
        return appendByKey(current, excel, ReportWorkload::getName, ReportExcelMerger::copyWorkloadRow);
    }

    public static List<ReportActivityRow> mergeHeat(List<ReportActivityRow> current, List<ReportActivityRow> excel,
            boolean overwrite)
    {
        Map<String, ReportActivityRow> bySite = new LinkedHashMap<>();
        if (current != null)
        {
            for (ReportActivityRow row : current)
            {
                if (row == null)
                {
                    continue;
                }
                bySite.put(normKey(row.getSite()), row);
            }
        }
        if (excel == null)
        {
            return new ArrayList<>(bySite.values());
        }
        for (ReportActivityRow incoming : excel)
        {
            if (incoming == null)
            {
                continue;
            }
            String key = normKey(incoming.getSite());
            if (key.isEmpty())
            {
                continue;
            }
            ReportActivityRow existing = bySite.get(key);
            if (existing == null)
            {
                bySite.put(key, newHeatSite(incoming));
                continue;
            }
            if (overwrite || heatAreaBlank(existing))
            {
                existing.setHeatingAreaM2(incoming.getHeatingAreaM2());
                existing.setHeatCoefficient(incoming.getHeatCoefficient());
            }
        }
        return new ArrayList<>(bySite.values());
    }

    public static String normKey(String value)
    {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    public static boolean heatAreaBlank(ReportActivityRow row)
    {
        return row.getHeatingAreaM2() == null && row.getHeatCoefficient() == null;
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

    private static <T> List<T> appendByKey(List<T> current, List<T> excel, Function<T, String> keyFn,
            Function<T, T> copier)
    {
        Map<String, T> merged = new LinkedHashMap<>();
        if (current != null)
        {
            for (T row : current)
            {
                if (row == null)
                {
                    continue;
                }
                merged.put(normKey(keyFn.apply(row)), row);
            }
        }
        if (excel != null)
        {
            for (T row : excel)
            {
                if (row == null)
                {
                    continue;
                }
                String key = normKey(keyFn.apply(row));
                if (key.isEmpty() || merged.containsKey(key))
                {
                    continue;
                }
                merged.put(key, copier.apply(row));
            }
        }
        return new ArrayList<>(merged.values());
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
