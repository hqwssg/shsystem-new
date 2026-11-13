package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.common.core.exception.ServiceException;

class ReportExcelParserTest
{
    @Test
    void parsesChineseAndEnglishHeaders()
    {
        byte[] data = ReportExcelParser.templateBytes(ReportExcelType.equipment);
        List<Map<String, String>> rows = ReportExcelParser.parse(new ByteArrayInputStream(data), ReportExcelType.equipment);
        assertTrue(rows.isEmpty());
    }

    @Test
    void parsesEquipmentRowWithoutInventingZero() throws Exception
    {
        org.apache.poi.xssf.usermodel.XSSFWorkbook book = new org.apache.poi.xssf.usermodel.XSSFWorkbook();
        org.apache.poi.ss.usermodel.Sheet sheet = book.createSheet();
        org.apache.poi.ss.usermodel.Row header = sheet.createRow(0);
        header.createCell(0).setCellValue("名称");
        header.createCell(1).setCellValue("数量");
        header.createCell(2).setCellValue("energy_type");
        org.apache.poi.ss.usermodel.Row row = sheet.createRow(1);
        row.createCell(0).setCellValue("线路维修车");
        row.createCell(2).setCellValue("柴油");
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        book.write(out);
        book.close();
        List<ReportEquipment> rows = ReportExcelParser.toEquipment(
                ReportExcelParser.parse(new ByteArrayInputStream(out.toByteArray()), ReportExcelType.equipment));
        assertEquals(1, rows.size());
        assertEquals("线路维修车", rows.get(0).getName());
        assertNull(rows.get(0).getQuantity());
        assertEquals("柴油", rows.get(0).getEnergyType());
        assertEquals("IMPORT", rows.get(0).getDataOrigin());
    }

    @Test
    void parsesHeatEnglishHeaders() throws Exception
    {
        org.apache.poi.xssf.usermodel.XSSFWorkbook book = new org.apache.poi.xssf.usermodel.XSSFWorkbook();
        org.apache.poi.ss.usermodel.Sheet sheet = book.createSheet();
        org.apache.poi.ss.usermodel.Row header = sheet.createRow(0);
        header.createCell(0).setCellValue("site");
        header.createCell(1).setCellValue("heating_area_m2");
        header.createCell(2).setCellValue("heat_coefficient");
        org.apache.poi.ss.usermodel.Row row = sheet.createRow(1);
        row.createCell(0).setCellValue("肃宁北站");
        row.createCell(1).setCellValue(12000);
        row.createCell(2).setCellValue(1.5);
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        book.write(out);
        book.close();
        List<ReportActivityRow> rows = ReportExcelParser.toHeat(
                ReportExcelParser.parse(new ByteArrayInputStream(out.toByteArray()), ReportExcelType.heat));
        assertEquals(1, rows.size());
        assertEquals("肃宁北站", rows.get(0).getSite());
        assertEquals(0, new BigDecimal("12000").compareTo(rows.get(0).getHeatingAreaM2()));
        assertEquals(0, new BigDecimal("1.5").compareTo(rows.get(0).getHeatCoefficient()));
        assertNull(rows.get(0).getNormalizedValue());
    }

    @Test
    void missingKeyColumnIsRejected() throws Exception
    {
        org.apache.poi.xssf.usermodel.XSSFWorkbook book = new org.apache.poi.xssf.usermodel.XSSFWorkbook();
        org.apache.poi.ss.usermodel.Sheet sheet = book.createSheet();
        sheet.createRow(0).createCell(0).setCellValue("数量");
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        book.write(out);
        book.close();
        ServiceException ex = assertThrows(ServiceException.class, () -> ReportExcelParser.parse(
                new ByteArrayInputStream(out.toByteArray()), ReportExcelType.equipment));
        assertTrue(ex.getMessage().contains("必填"));
    }

    @Test
    void profileEquipmentJsonKeepsNamesWithoutQuantity()
    {
        List<ReportEquipment> rows = ReportExcelImportService.fromEquipmentJson(null,
                "[{\"name\":\"档案车\",\"energy_type\":\"汽油\"}]");
        assertEquals(1, rows.size());
        assertEquals("档案车", rows.get(0).getName());
        assertNull(rows.get(0).getQuantity());
        assertEquals("MANUAL", rows.get(0).getDataOrigin());
    }
}
