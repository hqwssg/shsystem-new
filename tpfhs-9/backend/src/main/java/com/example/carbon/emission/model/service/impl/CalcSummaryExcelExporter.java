package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalcNodeSummary;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.streaming.SXSSFWorkbook;
import org.springframework.stereotype.Component;
import org.springframework.beans.factory.annotation.Autowired;
import com.example.carbon.emission.model.service.DataDictService;

import java.io.IOException;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

/** 将核算任务和汇总明细流式写入XLSX，不在服务器落盘。 */
@Component
public class CalcSummaryExcelExporter {
    @Autowired
    private DataDictService dataDictService;

    public void write(List<CalculationTemplate> tasks, List<CalcNodeSummary> rows, OutputStream output) throws IOException {
        try (SXSSFWorkbook workbook = new SXSSFWorkbook(200)) {
            workbook.setCompressTempFiles(true);
            writeTasks(workbook, tasks);
            writeSummaries(workbook, rows);
            workbook.write(output);
            workbook.dispose();
        }
    }

    private void writeTasks(Workbook wb, List<CalculationTemplate> tasks) {
        Sheet sheet = wb.createSheet("核算任务");
        String[] headers = {"任务ID", "核算模板ID", "周期开始", "周期结束", "状态", "发起方式", "发起人", "开始时间", "结束时间"};
        header(sheet, headers);
        int index = 1;
        for (CalculationTemplate task : tasks) {
            Row row = sheet.createRow(index++);
            cell(row, 0, task.getId()); cell(row, 1, task.getTemplateId());
            cell(row, 2, task.getCalculationCycleStartDate()); cell(row, 3, task.getCalculationCycleEndDate());
            cell(row, 4, task.getStatus()); cell(row, 5, task.getTaskInitiator());
            cell(row, 6, task.getInitiatorName()); cell(row, 7, task.getCalculationStartTime());
            cell(row, 8, task.getCalculationEndTime());
        }
        widths(sheet, headers.length);
    }

    private void writeSummaries(Workbook wb, List<CalcNodeSummary> rows) {
        Sheet sheet = wb.createSheet("汇总明细");
        Map<String, String> subcategories = dataDictService.getDictItems("emission_subcategory");
        String[] headers = {"任务ID", "快照节点ID", "源节点ID", "父节点ID", "节点层级", "小类", "L1", "L2", "L3",
                "直接活动量", "直接排放量", "子树活动量", "子树排放量", "核算单位", "等效因子", "数据来源"};
        header(sheet, headers);
        int index = 1;
        for (CalcNodeSummary item : rows) {
            Row row = sheet.createRow(index++);
            cell(row, 0, item.getCalculationTemplateId()); cell(row, 1, item.getCalculationNodeId());
            cell(row, 2, item.getSourceNodeId()); cell(row, 3, item.getParentCalcNodeId());
            String subcategoryName = subcategories.get(item.getEmissionSubcategory());
            cell(row, 4, item.getNodeLevel());
            cell(row, 5, subcategoryName == null || subcategoryName.isBlank() ? "未知排放小类" : subcategoryName);
            cell(row, 6, item.getEnergyCategoryL1()); cell(row, 7, item.getEnergyCategoryL2());
            cell(row, 8, item.getEnergyCategoryL3()); cell(row, 9, item.getDirectEnergyValue());
            cell(row, 10, item.getDirectCarbonEmission()); cell(row, 11, item.getSubtotalEnergyValue());
            cell(row, 12, item.getSubtotalCarbonEmission()); cell(row, 13, item.getCalculationUnitCode());
            cell(row, 14, item.getCarbonEmissionFactor()); cell(row, 15, item.getSummarySource());
        }
        widths(sheet, headers.length);
    }

    private void header(Sheet sheet, String[] headers) {
        Row row = sheet.createRow(0);
        for (int i = 0; i < headers.length; i++) row.createCell(i, CellType.STRING).setCellValue(headers[i]);
        sheet.createFreezePane(0, 1);
    }

    private void widths(Sheet sheet, int count) {
        for (int i = 0; i < count; i++) sheet.setColumnWidth(i, i >= 5 ? 18 * 256 : 14 * 256);
    }

    private void cell(Row row, int column, Object value) {
        Cell cell = row.createCell(column);
        if (value == null) return;
        // BigDecimal直接转double会丢失核算精度；以纯十进制文本写入，Excel/WPS
        // 展示值与API及数据库保持逐位一致，也不会触发科学计数法截断。
        if (value instanceof BigDecimal decimal) cell.setCellValue(decimal.toPlainString());
        else if (value instanceof Number number) cell.setCellValue(number.doubleValue());
        else if (value instanceof LocalDate date)
            cell.setCellValue(DateTimeFormatter.ISO_LOCAL_DATE.format(date));
        else if (value instanceof LocalDateTime dateTime)
            cell.setCellValue(DateTimeFormatter.ISO_LOCAL_DATE_TIME.format(dateTime));
        else cell.setCellValue(safe(String.valueOf(value)));
    }

    private String safe(String value) {
        return value.matches("^[=+@].*") || value.matches("^-[^0-9].*") ? "'" + value : value;
    }
}
