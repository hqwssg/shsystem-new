package com.ruoyi.carbon.report.source;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.common.core.constant.HttpStatus;
import com.ruoyi.common.core.exception.ServiceException;

/**
 * Parses report Excel templates. Empty cells stay empty; never invent 0.
 */
public final class ReportExcelParser
{
    private static final Map<String, String> ALIASES = new HashMap<>();

    static
    {
        alias("名称", "name");
        alias("name", "name");
        alias("类别", "category");
        alias("category", "category");
        alias("数量", "quantity");
        alias("quantity", "quantity");
        alias("单位", "unit");
        alias("unit", "unit");
        alias("型号", "model");
        alias("model", "model");
        alias("能源种类", "energyType");
        alias("energy_type", "energyType");
        alias("energyType", "energyType");
        alias("备注", "remark");
        alias("remark", "remark");
        alias("精度", "accuracy");
        alias("accuracy", "accuracy");
        alias("量程", "measurementRange");
        alias("measurement_range", "measurementRange");
        alias("measurementRange", "measurementRange");
        alias("位置", "location");
        alias("安装位置", "location");
        alias("location", "location");
        alias("规定校准频次", "calibrationFrequency");
        alias("检定周期", "calibrationFrequency");
        alias("calibration_frequency", "calibrationFrequency");
        alias("calibrationFrequency", "calibrationFrequency");
        alias("站点", "site");
        alias("site", "site");
        alias("供暖面积", "heatingAreaM2");
        alias("heating_area_m2", "heatingAreaM2");
        alias("heatingAreaM2", "heatingAreaM2");
        alias("热力系数", "heatCoefficient");
        alias("耗热量系数", "heatCoefficient");
        alias("heat_coefficient", "heatCoefficient");
        alias("heatCoefficient", "heatCoefficient");
    }

    private ReportExcelParser()
    {
    }

    public static byte[] templateBytes(ReportExcelType type)
    {
        try (XSSFWorkbook book = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream())
        {
            Sheet sheet = book.createSheet(type.label);
            Row header = sheet.createRow(0);
            for (int i = 0; i < type.headers.size(); i++)
            {
                header.createCell(i).setCellValue(type.headers.get(i));
                sheet.setColumnWidth(i, 18 * 256);
            }
            book.write(out);
            return out.toByteArray();
        }
        catch (IOException ex)
        {
            throw new ServiceException("无法生成模板", HttpStatus.ERROR);
        }
    }

    public static List<Map<String, String>> parse(InputStream in, ReportExcelType type)
    {
        try (Workbook book = WorkbookFactory.create(in))
        {
            Sheet sheet = book.getNumberOfSheets() > 0 ? book.getSheetAt(0) : null;
            if (sheet == null)
            {
                throw new ServiceException("空 Excel", HttpStatus.BAD_REQUEST);
            }
            Row headerRow = sheet.getRow(0);
            if (headerRow == null)
            {
                throw new ServiceException("空 Excel", HttpStatus.BAD_REQUEST);
            }
            DataFormatter formatter = new DataFormatter();
            Map<Integer, String> mapping = new LinkedHashMap<>();
            short last = headerRow.getLastCellNum();
            for (int i = 0; i < last; i++)
            {
                String header = normalizeHeader(formatter.formatCellValue(headerRow.getCell(i)));
                if (header != null)
                {
                    mapping.put(i, header);
                }
            }
            if (!mapping.containsValue(type.keyField))
            {
                throw new ServiceException("缺少必填列", HttpStatus.BAD_REQUEST);
            }
            List<Map<String, String>> rows = new ArrayList<>();
            for (int r = 1; r <= sheet.getLastRowNum(); r++)
            {
                Row row = sheet.getRow(r);
                if (row == null)
                {
                    continue;
                }
                Map<String, String> item = new LinkedHashMap<>();
                boolean any = false;
                for (Map.Entry<Integer, String> entry : mapping.entrySet())
                {
                    String value = cellText(formatter, row.getCell(entry.getKey()));
                    item.put(entry.getValue(), value);
                    if (value != null)
                    {
                        any = true;
                    }
                }
                if (any)
                {
                    rows.add(item);
                }
            }
            return rows;
        }
        catch (ServiceException ex)
        {
            throw ex;
        }
        catch (Exception ex)
        {
            throw new ServiceException("无法读取 Excel", HttpStatus.BAD_REQUEST);
        }
    }

    public static List<ReportEquipment> toEquipment(List<Map<String, String>> rows)
    {
        List<ReportEquipment> list = new ArrayList<>();
        for (Map<String, String> item : rows)
        {
            String name = text(item.get("name"));
            if (name == null)
            {
                continue;
            }
            ReportEquipment row = new ReportEquipment();
            row.setName(name);
            row.setCategory(nvl(item.get("category")));
            row.setQuantity(decimalOrNull(item.get("quantity")));
            row.setUnit(nvl(item.get("unit")));
            row.setModel(nvl(item.get("model")));
            row.setEnergyType(nvl(item.get("energyType")));
            row.setRemark(nvl(item.get("remark")));
            row.setDataOrigin("IMPORT");
            list.add(row);
        }
        return list;
    }

    public static List<ReportMonitoringDevice> toMonitoring(List<Map<String, String>> rows)
    {
        List<ReportMonitoringDevice> list = new ArrayList<>();
        for (Map<String, String> item : rows)
        {
            String name = text(item.get("name"));
            if (name == null)
            {
                continue;
            }
            ReportMonitoringDevice row = new ReportMonitoringDevice();
            row.setName(name);
            row.setModel(nvl(item.get("model")));
            row.setAccuracy(nvl(item.get("accuracy")));
            row.setMeasurementRange(nvl(item.get("measurementRange")));
            row.setLocation(nvl(item.get("location")));
            String freq = text(item.get("calibrationFrequency"));
            row.setCalibrationFrequency(freq == null ? "每年1次" : freq);
            row.setDataOrigin("IMPORT");
            list.add(row);
        }
        return list;
    }

    public static List<ReportWorkload> toWorkload(List<Map<String, String>> rows)
    {
        List<ReportWorkload> list = new ArrayList<>();
        for (Map<String, String> item : rows)
        {
            String name = text(item.get("name"));
            BigDecimal quantity = decimalOrNull(item.get("quantity"));
            if (name == null || quantity == null || quantity.compareTo(BigDecimal.ZERO) <= 0)
            {
                continue;
            }
            ReportWorkload row = new ReportWorkload();
            row.setName(name);
            row.setQuantity(quantity);
            row.setUnit(nvl(item.get("unit")));
            row.setDataOrigin("IMPORT");
            list.add(row);
        }
        return list;
    }

    public static List<ReportActivityRow> toHeat(List<Map<String, String>> rows)
    {
        List<ReportActivityRow> list = new ArrayList<>();
        for (Map<String, String> item : rows)
        {
            String site = text(item.get("site"));
            if (site == null)
            {
                continue;
            }
            ReportActivityRow row = new ReportActivityRow();
            row.setSite(site);
            row.setHeatingAreaM2(decimalOrNull(item.get("heatingAreaM2")));
            row.setHeatCoefficient(decimalOrNull(item.get("heatCoefficient")));
            row.setDataOrigin("IMPORT");
            list.add(row);
        }
        return list;
    }

    public static void requireUniqueKeys(List<String> keys, String label)
    {
        Map<String, Integer> seen = new HashMap<>();
        for (String key : keys)
        {
            String normalized = ReportExcelMerger.normKey(key);
            if (normalized.isEmpty())
            {
                continue;
            }
            if (seen.containsKey(normalized))
            {
                throw new ServiceException(label + "重复: " + key, HttpStatus.BAD_REQUEST);
            }
            seen.put(normalized, 1);
        }
    }

    static BigDecimal decimalOrNull(String raw)
    {
        String value = text(raw);
        if (value == null)
        {
            return null;
        }
        try
        {
            return new BigDecimal(value.replace(",", ""));
        }
        catch (NumberFormatException ex)
        {
            throw new ServiceException("数字格式无效: " + raw, HttpStatus.BAD_REQUEST);
        }
    }

    static String text(String raw)
    {
        if (raw == null)
        {
            return null;
        }
        String trimmed = raw.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static String nvl(String raw)
    {
        String value = text(raw);
        return value == null ? "" : value;
    }

    private static String cellText(DataFormatter formatter, Cell cell)
    {
        if (cell == null)
        {
            return null;
        }
        String value = formatter.formatCellValue(cell);
        return text(value);
    }

    private static String normalizeHeader(String raw)
    {
        String value = text(raw);
        if (value == null)
        {
            return null;
        }
        return ALIASES.get(value);
    }

    private static void alias(String from, String to)
    {
        ALIASES.put(from, to);
        ALIASES.put(from.toLowerCase(Locale.ROOT), to);
    }
}
