package com.ruoyi.carbon.report.generation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import org.junit.jupiter.api.Test;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;

class ReportSnapshotAssemblerTest
{
    @Test
    void omitsInternalSourceFromRendererMetadataWithoutChangingSavedReport()
    {
        for (String source : new String[] {
                "{\"deptId\":301,\"subjectNodeId\":1001,\"energyAllocation\":\"suring\"}",
                "{\"mode\":\"COMPANY\",\"deptId\":301,\"energyAllocation\":\"suring\"}" })
        {
            ReportTask task = new ReportTask();
            task.setReportYear(2025);
            task.setTitle("2025年度温室气体排放报告");
            String savedMetadata = "{\"entity_name\":\"肃宁分公司\",\"report_number\":\"TEST-2025\","
                    + "\"_report_subject\":" + source + "}";
            task.setMetadataJson(savedMetadata);
            ReportDraft draft = new ReportDraft();
            draft.setTask(task);

            JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));

            assertFalse(snapshot.getJSONObject("metadata").containsKey("_report_subject"));
            assertEquals("肃宁分公司", snapshot.getJSONObject("metadata").getString("entity_name"));
            assertEquals("TEST-2025", snapshot.getJSONObject("metadata").getString("report_number"));
            assertEquals(savedMetadata, task.getMetadataJson());
            assertTrue(JSON.parseObject(task.getMetadataJson()).containsKey("_report_subject"));
        }
    }

    @Test
    void snapshotContainsActivityNotRecomputedEmissions()
    {
        ReportTask task = new ReportTask();
        task.setDeptId(301L);
        task.setReportYear(2024);
        task.setTitle("2024年度温室气体排放报告");
        task.setMetadataJson("{\"entity_name\":\"肃宁分公司\",\"compiler\":\"编制\",\"compile_date\":\"2025-06-13\"}");
        task.setEntityProfileJson("{\"short_name\":\"肃宁\",\"business_description\":\"线路\",\"carbon_department\":\"安环\"}");
        ReportActivityRow fuel = new ReportActivityRow();
        fuel.setFuelType("diesel");
        fuel.setFacility("轨道车");
        fuel.setNormalizedValue(new java.math.BigDecimal("10"));
        fuel.setNormalizedUnit("t");
        fuel.setSourceName("轨道车");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getFuels().add(fuel);
        String json = new ReportSnapshotAssembler().assemble(draft, null);
        assertTrue(json.contains("\"fuel_type\":\"diesel\""));
        assertTrue(json.contains("\"quantity\":10"));
        assertTrue(!json.contains("recomputed"));
    }

    @Test
    void snapshotWritesProvidedFactors()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        java.util.Map<String, Object> factors = new java.util.LinkedHashMap<>();
        factors.put("source", "template");
        factors.put("electricity_factor_tco2_per_mwh", 0.5306);
        String json = new ReportSnapshotAssembler().assemble(draft, null, factors);
        assertTrue(json.contains("\"source\":\"template\""));
        assertTrue(json.contains("0.5306"));
    }

    @Test
    void fillsBlankBoundaryAndNotesFromProfileWithoutReplacingSavedRows()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2024);
        task.setTitle("2024年度温室气体排放报告");
        task.setOrganizationBoundaryJson("{\"emission_sources\":[\"化石燃料燃烧\"],"
                + "\"emission_source_rows\":[{\"category\":\"化石燃料燃烧\",\"facility\":\"食堂天然气灶\","
                + "\"location\":\"肃宁分公司食堂\",\"source\":\"天然气\"}]}");
        task.setEmissionBoundaryNotesJson("{}");
        ReportDeptProfile profile = new ReportDeptProfile();
        profile.setEntityCode("suning");
        profile.setDefaultOrgBoundary("8站3中心");
        profile.setDefaultAccountingMethod("陆上运输指南");
        profile.setDefaultExclusionNote("机车归机辆");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, profile));
        JSONObject boundary = snapshot.getJSONObject("organization_boundary");
        assertEquals("8站3中心", boundary.getString("boundary_description"));
        assertEquals("陆上运输指南", boundary.getString("accounting_method"));
        assertEquals("化石燃料燃烧", boundary.getJSONArray("emission_sources").getString(0));
        assertEquals("食堂天然气灶", boundary.getJSONArray("emission_source_rows").getJSONObject(0).getString("facility"));
        assertEquals("机车归机辆", snapshot.getJSONObject("emission_boundary_notes").getString("fuel_boundary_exclusion"));
    }

    @Test
    void doesNotOverwriteSavedBoundaryTextOrExclusion()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2024);
        task.setTitle("t");
        task.setOrganizationBoundaryJson("{\"boundary_description\":\"本年说明\",\"accounting_method\":\"本年方法\"}");
        task.setEmissionBoundaryNotesJson("{\"fuel_boundary_exclusion\":\"本年排除\"}");
        ReportDeptProfile profile = new ReportDeptProfile();
        profile.setDefaultOrgBoundary("档案说明");
        profile.setDefaultAccountingMethod("档案方法");
        profile.setDefaultExclusionNote("档案排除");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, profile));
        assertEquals("本年说明", snapshot.getJSONObject("organization_boundary").getString("boundary_description"));
        assertEquals("本年方法", snapshot.getJSONObject("organization_boundary").getString("accounting_method"));
        assertEquals("本年排除", snapshot.getJSONObject("emission_boundary_notes").getString("fuel_boundary_exclusion"));
    }

    @Test
    void fillsEquipmentFromProfileWhenDraftHasNone()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2024);
        task.setTitle("t");
        ReportDeptProfile profile = new ReportDeptProfile();
        profile.setDefaultEquipmentJson("[{\"name\":\"线路维修车\",\"category\":\"机械设备\",\"quantity\":12,"
                + "\"unit\":\"台\",\"model\":\"GC-270\",\"energy_type\":\"柴油\",\"remark\":\"检修\"}]");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, profile));
        JSONObject row = snapshot.getJSONArray("equipment").getJSONObject(0);
        assertEquals("线路维修车", row.getString("name"));
        assertEquals("GC-270", row.getString("model"));
        assertEquals("柴油", row.getString("energy_type"));
        assertEquals(12, row.getIntValue("quantity"));
    }

    @Test
    void doesNotOverwriteSavedEquipmentWithProfile()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2024);
        task.setTitle("t");
        ReportDeptProfile profile = new ReportDeptProfile();
        profile.setDefaultEquipmentJson("[{\"name\":\"档案车\",\"quantity\":12,\"energy_type\":\"柴油\"}]");
        ReportEquipment saved = new ReportEquipment();
        saved.setName("本年维修车");
        saved.setQuantity(new java.math.BigDecimal("11"));
        saved.setModel("GC-280");
        saved.setEnergyType("柴油");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getEquipment().add(saved);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, profile));
        JSONObject row = snapshot.getJSONArray("equipment").getJSONObject(0);
        assertEquals(1, snapshot.getJSONArray("equipment").size());
        assertEquals("本年维修车", row.getString("name"));
        assertEquals("GC-280", row.getString("model"));
        assertEquals(11, row.getIntValue("quantity"));
    }

    @Test
    void dropsSpecialNoteAndFallsBackToProfileProseWhenBlank()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        task.setActivityProseJson("{\"special_note\":\"旧稿\"}");
        ReportDeptProfile profile = new ReportDeptProfile();
        profile.setDefaultActivityProseJson("{\"natural_gas\":{\"usage\":\"天然气用于食堂灶具\"}}");
        profile.setDefaultChapter6Json("{\"emission_intensity\":{\"applicable\":false,\"not_applicable_note\":\"不涉及\"}}");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, profile));
        JSONObject prose = snapshot.getJSONObject("activity_prose");
        assertFalse(prose.containsKey("special_note"));
        assertEquals("天然气用于食堂灶具", prose.getJSONObject("natural_gas").getString("usage"));
        assertEquals(false, snapshot.getJSONObject("chapter6").getJSONObject("emission_intensity").getBoolean("applicable"));
    }

    @Test
    void omitsWorkloadWithoutQuantityAndWritesMonitoringFromDraft()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        ReportWorkload named = new ReportWorkload();
        named.setName("线路维修里程");
        named.setUnit("km");
        ReportWorkload filled = new ReportWorkload();
        filled.setName("检修作业天");
        filled.setQuantity(new java.math.BigDecimal("320"));
        filled.setUnit("天");
        ReportMonitoringDevice device = new ReportMonitoringDevice();
        device.setName("肃宁外购电表");
        device.setModel("DTZ341");
        device.setAccuracy("0.5S");
        device.setCalibrationFrequency("每年1次");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getWorkload().add(named);
        draft.getWorkload().add(filled);
        draft.getMonitoring().add(device);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        assertEquals(1, snapshot.getJSONArray("workload").size());
        assertEquals("检修作业天", snapshot.getJSONArray("workload").getJSONObject(0).getString("name"));
        JSONObject monitor = snapshot.getJSONArray("monitoring_devices").getJSONObject(0);
        assertEquals("肃宁外购电表", monitor.getString("name"));
        assertEquals("DTZ341", monitor.getString("model"));
        assertEquals("0.5S", monitor.getString("accuracy"));
        assertEquals("每年1次", monitor.getString("calibration_frequency"));
        assertFalse(monitor.containsKey("special_note"));
    }

    @Test
    void omitsPriorYearWhenTotalMissing()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        task.setPriorYearJson("{\"report_year\":2024}");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        assertFalse(snapshot.containsKey("prior_year"));
    }

    @Test
    void monthlySnapshotSplitsYoyAndMomAndWritesReportMonth()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setReportMonth(3);
        task.setPeriodType("MONTH");
        task.setTitle("2025年3月温室气体排放报告");
        task.setPriorYearJson("{\"yoy\":{\"report_year\":2024,\"report_month\":3,\"total_emissions_tco2\":10,"
                + "\"fuel_combustion_tco2\":4,\"electricity_emissions_tco2\":5,\"heat_emissions_tco2\":1},"
                + "\"mom\":{\"report_year\":2025,\"report_month\":2,\"total_emissions_tco2\":9,"
                + "\"fuel_combustion_tco2\":3,\"electricity_emissions_tco2\":4,\"heat_emissions_tco2\":2}}");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        assertEquals("month", snapshot.getString("period_grain"));
        assertEquals(3, snapshot.getJSONObject("metadata").getIntValue("report_month"));
        assertEquals(2024, snapshot.getJSONObject("prior_year").getIntValue("report_year"));
        assertEquals(3, snapshot.getJSONObject("prior_year").getIntValue("report_month"));
        assertEquals(2025, snapshot.getJSONObject("prior_month").getIntValue("report_year"));
        assertEquals(2, snapshot.getJSONObject("prior_month").getIntValue("report_month"));
        assertFalse(snapshot.getJSONObject("prior_year").containsKey("yoy"));
    }

    @Test
    void snapshotOmitsImagesWhenDraftHasNoStoredFiles()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        assertEquals(0, snapshot.getJSONArray("images").size());
    }

    @Test
    void snapshotUsesDefaultImageRow()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        ReportFile cover = new ReportFile();
        cover.setId(4L);
        cover.setRole("cover_logo");
        cover.setMimeType("image/png");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getDefaultImages().add(cover);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        assertEquals(1, snapshot.getJSONArray("images").size());
        assertEquals("carbon-file:4", snapshot.getJSONArray("images").getJSONObject(0).getString("url"));
    }

    @Test
    void snapshotUsesCarbonFileUrlWhenUploadPresent()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        ReportFile custom = new ReportFile();
        custom.setId(88L);
        custom.setRole("cover_logo");
        custom.setMimeType("image/png");
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getImages().add(custom);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        assertEquals(1, snapshot.getJSONArray("images").size());
        assertEquals("carbon-file:88", snapshot.getJSONArray("images").getJSONObject(0).getString("url"));
    }

    @Test
    void heatSnapshotWritesAreaAndCoefficientOnlyWhenPresent()
    {
        ReportTask task = new ReportTask();
        task.setReportYear(2025);
        task.setTitle("t");
        ReportActivityRow withArea = new ReportActivityRow();
        withArea.setSite("肃宁北站");
        withArea.setNormalizedValue(new java.math.BigDecimal("18000"));
        withArea.setHeatingAreaM2(new java.math.BigDecimal("12000"));
        withArea.setHeatCoefficient(new java.math.BigDecimal("1.5"));
        ReportActivityRow gjOnly = new ReportActivityRow();
        gjOnly.setSite("黄骅南站");
        gjOnly.setNormalizedValue(new java.math.BigDecimal("50"));
        ReportDraft draft = new ReportDraft();
        draft.setTask(task);
        draft.getHeat().add(withArea);
        draft.getHeat().add(gjOnly);
        JSONObject snapshot = JSON.parseObject(new ReportSnapshotAssembler().assemble(draft, null));
        JSONObject first = snapshot.getJSONArray("heat_activity").getJSONObject(0);
        JSONObject second = snapshot.getJSONArray("heat_activity").getJSONObject(1);
        assertEquals(0, new java.math.BigDecimal("12000").compareTo(first.getBigDecimal("heating_area_m2")));
        assertEquals(0, new java.math.BigDecimal("1.5").compareTo(first.getBigDecimal("heat_coefficient")));
        assertEquals(0, new java.math.BigDecimal("18000").compareTo(first.getBigDecimal("quantity_gj")));
        assertFalse(second.containsKey("heating_area_m2"));
        assertFalse(second.containsKey("heat_coefficient"));
        assertEquals(0, new java.math.BigDecimal("50").compareTo(second.getBigDecimal("quantity_gj")));
    }
}
