package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.common.core.exception.ServiceException;

class ReportExcelMergerTest
{
    @Test
    void equipmentOverwriteReplacesLookupRows()
    {
        ReportEquipment profile = namedEquipment("档案车", "汽油");
        profile.setDataOrigin("MANUAL");
        ReportEquipment excel = namedEquipment("导入车", "柴油");
        excel.setDataOrigin("IMPORT");
        List<ReportEquipment> merged = ReportExcelMerger.mergeEquipment(List.of(profile), List.of(excel), true);
        assertEquals(1, merged.size());
        assertEquals("导入车", merged.get(0).getName());
        assertEquals("IMPORT", merged.get(0).getDataOrigin());
    }

    @Test
    void equipmentAppendKeepsProfileAndAddsNew()
    {
        ReportEquipment profile = namedEquipment("档案车", "汽油");
        profile.setDataOrigin("MANUAL");
        ReportEquipment same = namedEquipment("档案车", "柴油");
        same.setDataOrigin("IMPORT");
        ReportEquipment extra = namedEquipment("新车", "电力");
        extra.setDataOrigin("IMPORT");
        List<ReportEquipment> merged = ReportExcelMerger.mergeEquipment(List.of(profile), List.of(same, extra), false);
        assertEquals(3, merged.size());
        assertEquals("档案车", merged.get(0).getName());
        assertEquals("汽油", merged.get(0).getEnergyType());
        assertEquals("MANUAL", merged.get(0).getDataOrigin());
        assertEquals("柴油", merged.get(1).getEnergyType());
        assertEquals("新车", merged.get(2).getName());
        assertEquals("IMPORT", merged.get(2).getDataOrigin());
    }

    @Test
    void monitoringAppendKeepsMeterSuggestions()
    {
        ReportMonitoringDevice suggested = new ReportMonitoringDevice();
        suggested.setName("肃宁外购电表");
        suggested.setDataOrigin("AUTO");
        ReportMonitoringDevice excel = new ReportMonitoringDevice();
        excel.setName("新增热表");
        excel.setAccuracy("0.5S");
        excel.setDataOrigin("IMPORT");
        List<ReportMonitoringDevice> merged = ReportExcelMerger.mergeMonitoring(List.of(suggested), List.of(excel), false);
        assertEquals(2, merged.size());
        assertEquals("肃宁外购电表", merged.get(0).getName());
        assertEquals("AUTO", merged.get(0).getDataOrigin());
        assertEquals("新增热表", merged.get(1).getName());
    }

    @Test
    void workloadSkipsNonPositiveWhenParsing()
    {
        java.util.Map<String, String> blankQty = new java.util.LinkedHashMap<>();
        blankQty.put("name", "线路维修里程");
        blankQty.put("quantity", "");
        java.util.Map<String, String> zero = new java.util.LinkedHashMap<>();
        zero.put("name", "检修作业天");
        zero.put("quantity", "0");
        java.util.Map<String, String> ok = new java.util.LinkedHashMap<>();
        ok.put("name", "检修作业天");
        ok.put("quantity", "320");
        ok.put("unit", "天");
        assertThrows(ServiceException.class, () -> ReportExcelParser.toWorkload(List.of(blankQty, zero, ok)));
        List<ReportWorkload> excel = ReportExcelParser.toWorkload(List.of(ok));
        assertEquals(1, excel.size());
        assertEquals(0, new BigDecimal("320").compareTo(excel.get(0).getQuantity()));
    }

    @Test
    void heatOverwriteDoesNotChangeGjAndAddsUnknownSite()
    {
        ReportActivityRow existing = heat("肃宁北站", "50", "12000", "1.5");
        existing.setId(11L);
        ReportActivityRow excelMatch = heat("肃宁北站", "999", "8000", "1.2");
        ReportActivityRow excelNew = heat("黄骅南站", "1", "100", "0.5");
        List<ReportActivityRow> merged = ReportExcelMerger.mergeHeat(List.of(existing), List.of(excelMatch, excelNew), true);
        assertEquals(2, merged.size());
        assertEquals(Long.valueOf(11L), merged.get(0).getId());
        assertEquals(0, new BigDecimal("50").compareTo(merged.get(0).getNormalizedValue()));
        assertEquals(0, new BigDecimal("8000").compareTo(merged.get(0).getHeatingAreaM2()));
        assertEquals("黄骅南站", merged.get(1).getSite());
        assertNull(merged.get(1).getNormalizedValue());
        assertNull(merged.get(1).getQuantity());
        assertEquals("IMPORT", merged.get(1).getDataOrigin());
    }

    @Test
    void heatAppendDoesNotOverwriteFilledArea()
    {
        ReportActivityRow filled = heat("肃宁北站", "50", "12000", "1.5");
        ReportActivityRow blank = heat("沧州西站", "20", null, null);
        ReportActivityRow excelFilled = heat("肃宁北站", "1", "1", "1");
        ReportActivityRow excelBlank = heat("沧州西站", "1", "3000", "0.8");
        List<ReportActivityRow> merged = ReportExcelMerger.mergeHeat(List.of(filled, blank), List.of(excelFilled, excelBlank), false);
        assertEquals(0, new BigDecimal("12000").compareTo(merged.get(0).getHeatingAreaM2()));
        assertEquals(0, new BigDecimal("50").compareTo(merged.get(0).getNormalizedValue()));
        assertEquals(0, new BigDecimal("3000").compareTo(merged.get(1).getHeatingAreaM2()));
        assertEquals(0, new BigDecimal("20").compareTo(merged.get(1).getNormalizedValue()));
    }

    @Test
    void duplicateExcelKeysAreRejected()
    {
        ServiceException ex = assertThrows(ServiceException.class,
                () -> ReportExcelParser.requireUniqueKeys(List.of("档案车", "档案车"), "设备名称"));
        assertTrue(ex.getMessage().contains("重复"));
    }

    @Test
    void emptyQuantityStaysNull()
    {
        java.util.Map<String, String> item = new java.util.LinkedHashMap<>();
        item.put("name", "办公用车");
        item.put("quantity", "");
        List<ReportEquipment> rows = ReportExcelParser.toEquipment(List.of(item));
        assertEquals(1, rows.size());
        assertNull(rows.get(0).getQuantity());
    }

    private static ReportEquipment namedEquipment(String name, String energy)
    {
        ReportEquipment row = new ReportEquipment();
        row.setName(name);
        row.setEnergyType(energy);
        return row;
    }

    private static ReportActivityRow heat(String site, String gj, String area, String coeff)
    {
        ReportActivityRow row = new ReportActivityRow();
        row.setSite(site);
        row.setNormalizedValue(gj == null ? null : new BigDecimal(gj));
        row.setQuantity(gj == null ? null : new BigDecimal(gj));
        row.setHeatingAreaM2(area == null ? null : new BigDecimal(area));
        row.setHeatCoefficient(coeff == null ? null : new BigDecimal(coeff));
        row.setDataOrigin("AUTO");
        return row;
    }
}
