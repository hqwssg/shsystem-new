package com.ruoyi.carbon.report.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportTask;

class ReportTaskServiceImplAssetsTest
{
    @Test
    void monitoringKeepsSameNamesExactDuplicatesAndUnnamedDevices()
    {
        ReportTask task = new ReportTask(); task.setId(9L); task.setDeptId(3030L);
        var rows = ReportTaskServiceImpl.parseMonitoringPayload(task,
                "{\"monitoring\":[{\"name\":\"电表\",\"model\":\"A\"},{\"name\":\"电表\",\"model\":\"A\"},"
                + "{\"name\":\"\",\"location\":\"2#进线\"},{}]}", "admin");
        assertEquals(3, rows.size());
        assertEquals("电表", rows.get(0).getName());
        assertEquals("电表", rows.get(1).getName());
        assertEquals("", rows.get(2).getName());
        assertEquals("2#进线", rows.get(2).getLocation());
    }

    @Test
    void monitoringLengthFailureHappensBeforeDeletingSavedRows()
    {
        ReportTaskServiceImpl service = new ReportTaskServiceImpl();
        var mapper = org.mockito.Mockito.mock(com.ruoyi.carbon.report.mapper.ReportMonitoringDeviceMapper.class);
        org.springframework.test.util.ReflectionTestUtils.setField(service, "reportMonitoringDeviceMapper", mapper);
        ReportTask task = new ReportTask(); task.setId(9L); task.setDeptId(3030L);
        String payload = "{\"monitoring\":[{}, {\"name\":\"电表\",\"measurementRange\":\"" + "测".repeat(65) + "\"}]}";
        var error = org.junit.jupiter.api.Assertions.assertThrows(com.ruoyi.common.core.exception.ServiceException.class,
                () -> org.springframework.test.util.ReflectionTestUtils.invokeMethod(service, "replaceMonitoring", task, payload, "admin"));
        assertTrue(error.getMessage().contains("第2行"));
        assertTrue(error.getMessage().contains("量程"));
        org.mockito.Mockito.verifyNoInteractions(mapper);
    }

    @Test
    void preservesUnknownEquipmentQuantityWithoutInventingZero()
    {
        ReportTask task = new ReportTask();task.setId(9L);task.setDeptId(3030L);
        var rows = ReportTaskServiceImpl.parseEquipmentPayload(task,
                "{\"equipment\":[{\"name\":\"未提供数量\",\"quantity\":null},"
                + "{\"name\":\"数量留空\",\"quantity\":\"\"},{\"name\":\"真实零\",\"quantity\":0}]}", "admin");
        assertEquals(3, rows.size());
        assertNull(rows.get(0).getQuantity());assertNull(rows.get(1).getQuantity());
        assertEquals(0, rows.get(2).getQuantity().signum());
    }

    @Test
    void parsesCamelAndSnakeEnergyTypeWithoutTouchingProfile()
    {
        ReportTask task = new ReportTask();
        task.setId(9L);
        task.setDeptId(301L);
        List<ReportEquipment> rows = ReportTaskServiceImpl.parseEquipmentPayload(task, "{"
                + "\"equipment\":["
                + "{\"name\":\"线路维修车\",\"category\":\"机械设备\",\"quantity\":11,\"unit\":\"台\","
                + "\"model\":\"GC-270\",\"energyType\":\"柴油\",\"remark\":\"本年\"},"
                + "{\"name\":\"办公用车\",\"quantity\":\"8\",\"energy_type\":\"汽油\"}"
                + "]}", "admin");
        assertEquals(2, rows.size());
        assertEquals(Long.valueOf(9L), rows.get(0).getReportId());
        assertEquals(Long.valueOf(301L), rows.get(0).getDeptId());
        assertEquals("线路维修车", rows.get(0).getName());
        assertEquals(0, new BigDecimal("11").compareTo(rows.get(0).getQuantity()));
        assertEquals("柴油", rows.get(0).getEnergyType());
        assertEquals("MANUAL", rows.get(0).getDataOrigin());
        assertEquals("汽油", rows.get(1).getEnergyType());
        assertEquals("办公用车", rows.get(1).getName());
    }

    @Test
    void skipsWorkloadWithoutPositiveQuantity()
    {
        ReportTask task = new ReportTask();
        task.setId(9L);
        task.setDeptId(301L);
        var rows = ReportTaskServiceImpl.parseWorkloadPayload(task, "{"
                + "\"workload\":["
                + "{\"name\":\"线路维修里程\",\"unit\":\"km\"},"
                + "{\"name\":\"检修作业天\",\"quantity\":320,\"unit\":\"天\"}"
                + "]}", "admin");
        assertEquals(1, rows.size());
        assertEquals("检修作业天", rows.get(0).getName());
        assertEquals("MANUAL", rows.get(0).getDataOrigin());
        assertEquals(0, new BigDecimal("320").compareTo(rows.get(0).getQuantity()));
    }

    @Test
    void parsesMonitoringCamelAndSnakeFields()
    {
        ReportTask task = new ReportTask();
        task.setId(9L);
        task.setDeptId(301L);
        var rows = ReportTaskServiceImpl.parseMonitoringPayload(task, "{"
                + "\"monitoring\":["
                + "{\"name\":\"肃宁外购电表\",\"model\":\"DTZ341\",\"accuracy\":\"0.5S\","
                + "\"calibrationFrequency\":\"每年1次\",\"measurement_range\":\"0-100\"},"
                + "{\"name\":\"\"}"
                + "]}", "admin");
        assertEquals(1, rows.size());
        assertEquals("肃宁外购电表", rows.get(0).getName());
        assertEquals("DTZ341", rows.get(0).getModel());
        assertEquals("每年1次", rows.get(0).getCalibrationFrequency());
        assertEquals("0-100", rows.get(0).getMeasurementRange());
        assertEquals("MANUAL", rows.get(0).getDataOrigin());
    }

    @Test
    void priorYearPayloadKeepsFourNumbersAndExtractsFromSnapshotTrend()
    {
        String json = ReportTaskServiceImpl.applyPriorYearPayload("{"
                + "\"report_year\":2024,"
                + "\"total_emissions_tco2\":100,"
                + "\"fuel_combustion_tco2\":40,"
                + "\"electricity_emissions_tco2\":50,"
                + "\"heat_emissions_tco2\":10,"
                + "\"noise\":true"
                + "}");
        assertTrue(json.contains("\"report_year\":2024"));
        assertTrue(json.contains("total_emissions_tco2"));
        assertFalse(json.contains("noise"));
        String fromSnap = ReportTaskServiceImpl.extractPriorFromSnapshot("{"
                + "\"chapter6\":{\"trend_years\":[{\"year\":2024,\"total_emissions_tco2\":88,"
                + "\"fuel_combustion_tco2\":10,\"electricity_emissions_tco2\":20,\"heat_emissions_tco2\":58}]}"
                + "}", 2024);
        assertTrue(fromSnap.contains("\"report_year\":2024"));
        assertTrue(fromSnap.contains("88"));
    }

    @Test
    void monthlyPriorPayloadKeepsYoyAndMomAndDropsNoise()
    {
        String json = ReportTaskServiceImpl.applyPriorYearPayload("{"
                + "\"yoy\":{\"report_year\":2024,\"report_month\":3,\"total_emissions_tco2\":10,"
                + "\"fuel_combustion_tco2\":4,\"electricity_emissions_tco2\":5,\"heat_emissions_tco2\":1,\"noise\":1},"
                + "\"mom\":{\"report_year\":2025,\"report_month\":2,\"total_emissions_tco2\":9}"
                + "}");
        assertTrue(json.contains("\"yoy\""));
        assertTrue(json.contains("\"mom\""));
        assertTrue(json.contains("\"report_month\":3"));
        assertFalse(json.contains("noise"));
        assertTrue(ReportTaskServiceImpl.isMonthlyComparisonJson(json));
        assertFalse(ReportTaskServiceImpl.isMonthlyComparisonJson(
                "{\"report_year\":2024,\"total_emissions_tco2\":100}"));
        int[] jan = ReportTaskServiceImpl.previousMonth(2025, 1);
        assertEquals(2024, jan[0]);
        assertEquals(12, jan[1]);
        int[] mar = ReportTaskServiceImpl.previousMonth(2025, 3);
        assertEquals(2025, mar[0]);
        assertEquals(2, mar[1]);
    }

    @Test
    void heatAreaPayloadDoesNotTouchQuantity()
    {
        ReportTask task = new ReportTask();
        task.setId(9L);
        task.setDeptId(301L);
        List<ReportActivityRow> rows = ReportTaskServiceImpl.parseHeatAreaPayload(task, "{"
                + "\"heat\":["
                + "{\"id\":11,\"heatingAreaM2\":12000,\"heatCoefficient\":1.5,\"quantity\":999,\"normalizedValue\":50},"
                + "{\"id\":12,\"heating_area_m2\":\"\",\"heat_coefficient\":\"\"}"
                + "]}", "admin");
        assertEquals(2, rows.size());
        assertEquals(Long.valueOf(11L), rows.get(0).getId());
        assertEquals(0, new BigDecimal("12000").compareTo(rows.get(0).getHeatingAreaM2()));
        assertEquals(0, new BigDecimal("1.5").compareTo(rows.get(0).getHeatCoefficient()));
        assertNull(rows.get(0).getQuantity());
        assertNull(rows.get(0).getNormalizedValue());
        assertNull(rows.get(1).getHeatingAreaM2());
        assertNull(rows.get(1).getHeatCoefficient());
        assertEquals("admin", rows.get(0).getUpdateBy());
    }

    @Test
    void invalidWorkloadAndDuplicateIndicatorsAreNotSilentlyDropped() {
        ReportTask task=new ReportTask();task.setId(9L);task.setDeptId(301L);
        org.junit.jupiter.api.Assertions.assertThrows(com.ruoyi.common.core.exception.ServiceException.class,
            () -> ReportTaskServiceImpl.parseWorkloadPayload(task,"{\"workload\":[{\"name\":\"\",\"quantity\":1}]}","admin"));
        org.junit.jupiter.api.Assertions.assertThrows(com.ruoyi.common.core.exception.ServiceException.class,
            () -> ReportTaskServiceImpl.parseWorkloadPayload(task,"{\"workload\":[{\"name\":\"指标\",\"quantity\":1},{\"name\":\"指标\",\"quantity\":2}]}","admin"));
    }

    @Test
    void newHeatSiteNeverAcceptsClientQuantityAndForeignIdWritesNothing() {
        ReportTask task=new ReportTask();task.setId(9L);task.setDeptId(301L);
        ReportTaskServiceImpl service=new ReportTaskServiceImpl();
        var mapper=org.mockito.Mockito.mock(com.ruoyi.carbon.report.mapper.ReportActivityMapper.class);
        org.springframework.test.util.ReflectionTestUtils.setField(service,"reportActivityMapper",mapper);
        org.mockito.Mockito.when(mapper.selectHeat(9L,301L)).thenReturn(java.util.List.of());
        org.springframework.test.util.ReflectionTestUtils.invokeMethod(service,"updateHeatArea",task,
            "{\"heat\":[{\"site\":\"新增站\",\"heatingAreaM2\":100,\"normalizedValue\":999,\"quantity\":999}]}","admin");
        var capture=org.mockito.ArgumentCaptor.forClass(ReportActivityRow.class);
        org.mockito.Mockito.verify(mapper).insertHeat(capture.capture());
        assertNull(capture.getValue().getQuantity());assertNull(capture.getValue().getNormalizedValue());
        assertEquals("新增站",capture.getValue().getSite());assertEquals("IMPORT",capture.getValue().getDataOrigin());
        org.mockito.Mockito.clearInvocations(mapper);
        org.junit.jupiter.api.Assertions.assertThrows(com.ruoyi.common.core.exception.ServiceException.class,
            () -> org.springframework.test.util.ReflectionTestUtils.invokeMethod(service,"updateHeatArea",task,
                "{\"heat\":[{\"id\":999,\"heatingAreaM2\":1}]}","admin"));
        org.mockito.Mockito.verify(mapper,org.mockito.Mockito.never()).updateHeatArea(org.mockito.ArgumentMatchers.any());
        org.mockito.Mockito.verify(mapper,org.mockito.Mockito.never()).insertHeat(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void invalidEquipmentCannotDeleteExistingRows() {
        ReportTask task=new ReportTask();task.setId(9L);task.setDeptId(301L);
        ReportTaskServiceImpl service=new ReportTaskServiceImpl();
        var mapper=org.mockito.Mockito.mock(com.ruoyi.carbon.report.mapper.ReportEquipmentMapper.class);
        org.springframework.test.util.ReflectionTestUtils.setField(service,"reportEquipmentMapper",mapper);
        String json="{\"equipment\":[{\"name\":\"设备\",\"model\":\"" + "字".repeat(129) + "\"}]}";
        org.junit.jupiter.api.Assertions.assertThrows(com.ruoyi.common.core.exception.ServiceException.class,
            () -> org.springframework.test.util.ReflectionTestUtils.invokeMethod(service,"replaceEquipment",task,json,"admin"));
        org.mockito.Mockito.verifyNoInteractions(mapper);
    }
}
