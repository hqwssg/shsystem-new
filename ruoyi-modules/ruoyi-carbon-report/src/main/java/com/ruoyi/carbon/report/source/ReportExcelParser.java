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
import org.apache.poi.ss.usermodel.FormulaEvaluator;
import org.apache.poi.ss.usermodel.CellValue;
import org.apache.poi.ss.usermodel.CellType;
import org.apache.poi.ss.util.CellRangeAddress;
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
            FormulaEvaluator evaluator = book.getCreationHelper().createFormulaEvaluator();
            Map<Integer, String> mapping = new LinkedHashMap<>();
            short last = headerRow.getLastCellNum();
            for (int i = 0; i < last; i++)
            {
                String header = normalizeHeader(formatter.formatCellValue(headerRow.getCell(i)));
                if (header != null && type.headers.stream().map(ReportExcelParser::normalizeHeader).anyMatch(header::equals))
                {
                    if (mapping.containsValue(header)) throw new ServiceException("Excel第1行存在重复表头：" + formatter.formatCellValue(headerRow.getCell(i)), HttpStatus.BAD_REQUEST);
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
                    Cell cell = row.getCell(entry.getKey());
                    // A vertically merged equipment description labels every physical row beneath it.
                    if (type == ReportExcelType.equipment) {
                        for (CellRangeAddress merged : sheet.getMergedRegions()) {
                            if (merged.getFirstColumn() == entry.getKey() && merged.getLastColumn() == entry.getKey()
                                    && merged.getFirstRow() < r && merged.getLastRow() >= r) {
                                cell = sheet.getRow(merged.getFirstRow()).getCell(entry.getKey());
                                break;
                            }
                        }
                    }
                    String value;
                    try { value = cellText(formatter, evaluator, cell, List.of("quantity", "heatingAreaM2", "heatCoefficient").contains(entry.getValue())); }
                    catch (Exception ex) { throw new ServiceException("Excel第" + (r + 1) + "行“" + headerRow.getCell(entry.getKey()) + "”公式或单元格错误，请计算保存或粘贴为数值", HttpStatus.BAD_REQUEST); }
                    item.put(entry.getValue(), value);
                    if (value != null)
                    {
                        any = true;
                    }
                }
                if (any)
                {
                    item.put("_excelRow", String.valueOf(r + 1));
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
            String name = nvl(item.get("name"));
            ReportEquipment row = new ReportEquipment();
            row.setName(name);
            row.setCategory(nvl(item.get("category")));
            row.setQuantity(decimal(item, "quantity", "数量"));
            row.setUnit(nvl(item.get("unit")));
            row.setModel(nvl(item.get("model")));
            row.setEnergyType(nvl(item.get("energyType")));
            row.setRemark(nvl(item.get("remark")));
            row.setDataOrigin("IMPORT");
            validateEquipment(row, rowNumber(item));
            if (hasContent(item)) list.add(row);
        }
        return list;
    }

    public static List<ReportMonitoringDevice> toMonitoring(List<Map<String, String>> rows)
    {
        List<ReportMonitoringDevice> list = new ArrayList<>();
        for (Map<String, String> item : rows)
        {
            String name = nvl(item.get("name"));
            ReportMonitoringDevice row = new ReportMonitoringDevice();
            row.setName(name);
            row.setModel(nvl(item.get("model")));
            row.setAccuracy(nvl(item.get("accuracy")));
            row.setMeasurementRange(nvl(item.get("measurementRange")));
            row.setLocation(nvl(item.get("location")));
            String freq = text(item.get("calibrationFrequency"));
            row.setCalibrationFrequency(freq == null ? "" : freq);
            row.setDataOrigin("IMPORT");
            if (!ReportMonitoringRules.isBlank(row)) list.add(row);
        }
        return list;
    }

    public static List<ReportWorkload> toWorkload(List<Map<String, String>> rows)
    {
        List<ReportWorkload> list = new ArrayList<>();
        for (Map<String, String> item : rows)
        {
            String name = text(item.get("name"));
            BigDecimal quantity = decimal(item, "quantity", "数量");
            if (name == null || quantity == null || quantity.compareTo(BigDecimal.ZERO) <= 0)
            {
                throw new ServiceException("Excel第" + rowNumber(item) + "行工作量需填写名称和正数量，请核对或移除该行", HttpStatus.BAD_REQUEST);
            }
            ReportWorkload row = new ReportWorkload();
            row.setName(name);
            row.setQuantity(quantity);
            row.setUnit(nvl(item.get("unit")));
            row.setDataOrigin("IMPORT");
            validateWorkload(row, rowNumber(item));
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
            if (site == null) throw new ServiceException("Excel第" + rowNumber(item) + "行缺少站点", HttpStatus.BAD_REQUEST);
            ReportActivityRow row = new ReportActivityRow();
            row.setSite(site);
            row.setHeatingAreaM2(decimal(item, "heatingAreaM2", "供暖面积"));
            row.setHeatCoefficient(decimal(item, "heatCoefficient", "耗热量系数"));
            validateHeat(row, rowNumber(item));
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

    private static int rowNumber(Map<String, String> item) { return Integer.parseInt(item.getOrDefault("_excelRow", "1")); }

    private static boolean hasContent(Map<String, String> item) {
        return item.entrySet().stream().anyMatch(e -> !e.getKey().startsWith("_") && text(e.getValue()) != null);
    }

    private static BigDecimal decimal(Map<String, String> item, String key, String label) {
        try { return decimalOrNull(item.get(key)); }
        catch (ServiceException ex) { throw new ServiceException("Excel第" + rowNumber(item) + "行“" + label + "”：" + ex.getMessage(), HttpStatus.BAD_REQUEST); }
    }

    public static void validateEquipment(ReportEquipment row, int number) {
        length(row.getName(), 255, "设备名称", number);
        length(row.getCategory(), 64, "设备类别", number);
        length(row.getModel(), 128, "型号", number);
        length(row.getUnit(), 32, "设备单位", number);
        length(row.getEnergyType(), 64, "能源种类", number);
        length(row.getRemark(), 255, "备注", number);
        amount(row.getQuantity(), 4, "设备数量", number);
    }

    public static void validateWorkload(ReportWorkload row, int number) {
        length(row.getName(), 128, "工作量名称", number);
        length(row.getUnit(), 32, "工作量单位", number);
        amount(row.getQuantity(), 6, "工作量数量", number);
    }

    public static void validateHeat(ReportActivityRow row, int number) {
        length(row.getSite(), 255, "站点", number);
        amount(row.getHeatingAreaM2(), 6, "供暖面积", number);
        amount(row.getHeatCoefficient(), 6, "耗热量系数", number);
    }

    private static void length(String value, int max, String label, int row) {
        if (value != null && value.codePointCount(0, value.length()) > max)
            throw new ServiceException("第" + row + "行“" + label + "”超过" + max + "字，请修改后保存", HttpStatus.BAD_REQUEST);
    }

    private static void amount(BigDecimal value, int scale, String label, int row) {
        if (value != null && (value.signum() < 0 || value.stripTrailingZeros().scale() > scale
                || value.abs().compareTo(BigDecimal.TEN.pow(18 - scale)) >= 0))
            throw new ServiceException("第" + row + "行“" + label + "”需为非负数字，整数最多" + (18 - scale) + "位，小数最多" + scale + "位", HttpStatus.BAD_REQUEST);
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

    private static String cellText(DataFormatter formatter, FormulaEvaluator evaluator, Cell cell, boolean numeric)
    {
        if (cell == null)
        {
            return null;
        }
        if (cell.getCellType() == CellType.ERROR) throw new IllegalArgumentException("错误单元格");
        if (cell.getCellType() == CellType.FORMULA) {
            CellValue value = evaluator.evaluate(cell);
            if (value == null || value.getCellType() == CellType.ERROR) throw new IllegalArgumentException("公式错误");
            if (numeric && value.getCellType() == CellType.NUMERIC) return BigDecimal.valueOf(value.getNumberValue()).stripTrailingZeros().toPlainString();
            return text(formatter.formatCellValue(cell, evaluator));
        }
        if (numeric && cell.getCellType() == CellType.NUMERIC) return BigDecimal.valueOf(cell.getNumericCellValue()).stripTrailingZeros().toPlainString();
        return text(formatter.formatCellValue(cell));
    }

    private static String normalizeHeader(String raw)
    {
        String value = text(raw);
        if (value == null)
        {
            return null;
        }
        return ALIASES.get(value.toLowerCase(Locale.ROOT));
    }

    private static void alias(String from, String to)
    {
        ALIASES.put(from, to);
        ALIASES.put(from.toLowerCase(Locale.ROOT), to);
    }
}
