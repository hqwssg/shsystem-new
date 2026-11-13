package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.*;
import java.io.*;
import java.math.BigDecimal;
import java.util.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.ss.util.CellRangeAddress;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.common.core.exception.ServiceException;

class ReportExcelSafetyTest {
    private List<Map<String,String>> parse(XSSFWorkbook book, ReportExcelType type) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); book.write(out);
        return ReportExcelParser.parse(new ByteArrayInputStream(out.toByteArray()), type);
    }

    @Test void equipmentKeepsRepeatedAndUnnamedRows() {
        var excel = ReportExcelParser.toEquipment(List.of(Map.of("name", "空压机", "model", "A"),
                Map.of("name", "空压机", "model", "B"), Map.of("model", "C")));
        excel.get(0).setSourceId("original-source");
        var rows = ReportExcelMerger.mergeEquipment(List.of(excel.get(0), excel.get(1)), excel, false);
        assertEquals(5, rows.size()); assertEquals("", rows.get(4).getName());
        assertEquals("A", rows.get(0).getModel()); assertEquals("B", rows.get(1).getModel());
        assertEquals("original-source", rows.get(0).getSourceId());
    }

    @Test void formulaUsesResultAndNumericErrorPointsToRow() throws Exception {
        try (XSSFWorkbook book = new XSSFWorkbook()) {
            Sheet s = book.createSheet(); Row h=s.createRow(0); h.createCell(0).setCellValue("名称"); h.createCell(1).setCellValue("数量");
            Row r=s.createRow(1);r.createCell(0).setCellValue("设备");r.createCell(1).setCellFormula("1+2");
            assertEquals(0, new BigDecimal("3").compareTo(ReportExcelParser.toEquipment(parse(book, ReportExcelType.equipment)).get(0).getQuantity()));
            r.removeCell(r.getCell(1)); r.createCell(1).setCellValue("不是数量");
            var error = assertThrows(ServiceException.class, () -> ReportExcelParser.toEquipment(parse(book, ReportExcelType.equipment)));
            assertTrue(error.getMessage().contains("第2行")); assertTrue(error.getMessage().contains("数量"));
        }
    }

    @Test void duplicateAliasesAndBrokenFormulaAreRejected() throws Exception {
        try (XSSFWorkbook book = new XSSFWorkbook()) {
            Sheet s=book.createSheet();Row h=s.createRow(0);h.createCell(0).setCellValue("名称");h.createCell(1).setCellValue("数量");h.createCell(2).setCellValue("QUANTITY");
            assertTrue(assertThrows(ServiceException.class, () -> parse(book, ReportExcelType.equipment)).getMessage().contains("重复表头"));
            h.removeCell(h.getCell(2));Row r=s.createRow(1);r.createCell(0).setCellValue("设备");r.createCell(1).setCellFormula("1/0");
            assertTrue(assertThrows(ServiceException.class, () -> parse(book, ReportExcelType.equipment)).getMessage().contains("第2行"));
        }
    }

    @Test void mergedEquipmentDescriptionsPreserveEveryModel() throws Exception {
        try (XSSFWorkbook book = new XSSFWorkbook()) {
            Sheet s=book.createSheet();Row h=s.createRow(0);h.createCell(0).setCellValue("名称");h.createCell(1).setCellValue("型号");
            s.createRow(1).createCell(0).setCellValue("电表");s.getRow(1).createCell(1).setCellValue("A");s.createRow(2).createCell(1).setCellValue("B");
            s.addMergedRegion(new CellRangeAddress(1,2,0,0));
            var rows=ReportExcelParser.toEquipment(parse(book, ReportExcelType.equipment));
            assertEquals(2,rows.size());assertEquals("电表",rows.get(1).getName());assertEquals("B",rows.get(1).getModel());
        }
    }

    @Test void formattedIdentifiersKeepTheirLeadingZeros() throws Exception {
        try (XSSFWorkbook book = new XSSFWorkbook()) {
            Sheet s=book.createSheet();Row h=s.createRow(0);h.createCell(0).setCellValue("名称");h.createCell(1).setCellValue("型号");
            Row r=s.createRow(1);r.createCell(0).setCellValue("设备");r.createCell(1).setCellValue(1);
            CellStyle style=book.createCellStyle();style.setDataFormat(book.createDataFormat().getFormat("0000"));r.getCell(1).setCellStyle(style);
            assertEquals("0001",ReportExcelParser.toEquipment(parse(book,ReportExcelType.equipment)).get(0).getModel());
        }
    }

    private ReportWorkload work(String name, String value, String unit) {
        ReportWorkload row=new ReportWorkload();row.setName(name);row.setQuantity(value==null?null:new BigDecimal(value));row.setUnit(unit);return row;
    }

    @Test void workloadFillsBlankQuantityWithoutAddingDuplicates() {
        var blank=work("周转量",null,"吨公里");
        var rows=ReportExcelMerger.mergeWorkload(List.of(blank),List.of(work("周转量","100","吨公里"),work("周转量","100.00","吨公里")),false);
        assertEquals(1,rows.size());assertEquals(0,new BigDecimal("100").compareTo(rows.get(0).getQuantity()));
        assertNull(blank.getQuantity(), "Preview merging must not mutate its inputs");
    }

    @Test void workloadNeverSumsConflictingUnitsOrQuantities() {
        assertThrows(ServiceException.class, () -> ReportExcelMerger.mergeWorkload(List.of(work("指标","1","km")), List.of(work("指标","1","m")), false));
        assertThrows(ServiceException.class, () -> ReportExcelMerger.mergeWorkload(List.of(work("指标","1","km")), List.of(work("指标","2","km")), false));
        assertThrows(ServiceException.class, () -> ReportExcelMerger.mergeWorkload(List.of(), List.of(work("指标","1","km"),work("指标","2","km")), true));
        assertThrows(ServiceException.class, () -> ReportExcelParser.toWorkload(List.of(Map.of("name","指标","quantity","0","_excelRow","7"))));
    }

    private ReportActivityRow heat(String area, String coefficient) {
        ReportActivityRow r=new ReportActivityRow();r.setId(11L);r.setSite("站点");r.setNormalizedValue(new BigDecimal("50"));
        r.setHeatingAreaM2(area==null?null:new BigDecimal(area));r.setHeatCoefficient(coefficient==null?null:new BigDecimal(coefficient));return r;
    }

    @Test void heatFillsEachBlankAndKeepsGjAndUnspecifiedValues() {
        ReportActivityRow original=heat("100",null);
        var result=ReportExcelMerger.mergeHeat(List.of(original),List.of(heat(null,"0.8")),false).get(0);
        assertEquals(new BigDecimal("100"),result.getHeatingAreaM2());assertEquals(new BigDecimal("0.8"),result.getHeatCoefficient());
        assertEquals(new BigDecimal("50"),result.getNormalizedValue());assertNull(original.getHeatCoefficient());
        result=ReportExcelMerger.mergeHeat(List.of(result),List.of(heat("200",null)),true).get(0);
        assertEquals(new BigDecimal("200"),result.getHeatingAreaM2());assertEquals(new BigDecimal("0.8"),result.getHeatCoefficient());
        assertThrows(ServiceException.class, () -> ReportExcelMerger.mergeHeat(List.of(original,heat("200",null)),List.of(heat(null,"1")),true));
    }
}
