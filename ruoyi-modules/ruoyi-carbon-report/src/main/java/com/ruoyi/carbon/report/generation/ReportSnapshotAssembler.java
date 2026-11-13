package com.ruoyi.carbon.report.generation;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONArray;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;
import com.ruoyi.carbon.report.domain.ReportEquipment;
import com.ruoyi.carbon.report.domain.ReportFile;
import com.ruoyi.carbon.report.domain.ReportMonitoringDevice;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;
import com.ruoyi.carbon.report.source.ReportSubjectSnapshot;
import com.ruoyi.carbon.report.source.ReportPeriodSnapshot;

/**
 * Builds an immutable ReportInput-shaped snapshot. Does not recompute emissions.
 */
public class ReportSnapshotAssembler
{
    public String assemble(ReportDraft draft, ReportDeptProfile profile)
    {
        return assemble(draft, profile, null);
    }

    public String assemble(ReportDraft draft, ReportDeptProfile profile, Map<String, Object> factors)
    {
        return assemble(draft, profile, factors, List.of(), List.of());
    }

    public String assemble(ReportDraft draft, ReportDeptProfile profile, Map<String, Object> factors,
            List<Map<String, Object>> monthlyFuel, List<Map<String, Object>> monthlyElectricity)
    {
        ReportTask task = draft.getTask();
        JSONObject metadata = parse(task.getMetadataJson());
        // Keep source ownership in the saved report, outside the renderer's strict metadata schema.
        metadata.keySet().removeIf(key -> key.startsWith("_"));
        JSONObject entity = parse(task.getEntityProfileJson());
        JSONObject boundary = parse(task.getOrganizationBoundaryJson());
        JSONObject notes = parse(task.getEmissionBoundaryNotesJson());
        JSONObject prose = ActivityProseSanitizer.sanitize(task.getActivityProseJson());
        JSONObject chapter6 = parse(task.getChapter6Json());
        if (profile != null)
        {
            metadata.putIfAbsent("entity_name", nvl(profile.getLegalName()));
            metadata.putIfAbsent("compiler", nvl(profile.getDefaultCompiler()));
            metadata.putIfAbsent("approver", nvl(profile.getDefaultApprover()));
            metadata.putIfAbsent("validator", nvl(profile.getDefaultValidator()));
            metadata.putIfAbsent("reviewer", nvl(profile.getDefaultReviewer()));
            metadata.putIfAbsent("checker", nvl(profile.getDefaultChecker()));
            metadata.putIfAbsent("authors", nvl(profile.getDefaultAuthors()));
            metadata.putIfAbsent("header_text", nvl(profile.getHeaderTemplate()));
            entity.putIfAbsent("short_name", nvl(profile.getShortName()));
            entity.putIfAbsent("business_description", nvl(profile.getBusinessDescription()));
            entity.putIfAbsent("carbon_department", nvl(profile.getCarbonDepartment()));
            entity.putIfAbsent("company_overview", nvl(profile.getCompanyOverview()));
            entity.putIfAbsent("process_description", nvl(profile.getProcessDescription()));
            fillIfBlank(boundary, "boundary_description", profile.getDefaultOrgBoundary());
            fillIfBlank(boundary, "accounting_method", profile.getDefaultAccountingMethod());
            fillIfBlank(notes, "fuel_boundary_exclusion", profile.getDefaultExclusionNote());
            if (ActivityProseSanitizer.isBlank(prose))
            {
                prose = ActivityProseSanitizer.sanitize(profile.getDefaultActivityProseJson());
            }
            if (chapter6.isEmpty() || chapter6.getJSONObject("emission_intensity") == null)
            {
                JSONObject fromProfile = parse(profile.getDefaultChapter6Json());
                if (!fromProfile.isEmpty())
                {
                    chapter6 = fromProfile;
                }
            }
        }
        metadata.putIfAbsent("entity_name", nvl(task.getTitle()));
        metadata.putIfAbsent("report_year", task.getReportYear());
        if ("MONTH".equalsIgnoreCase(task.getPeriodType()) && task.getReportMonth() != null)
        {
            metadata.putIfAbsent("report_month", task.getReportMonth());
        }
        metadata.putIfAbsent("report_period", task.getTitle());
        metadata.putIfAbsent("compiler", "");
        metadata.putIfAbsent("compile_date", LocalDate.now().toString());
        JSONObject contract = ReportPeriodSnapshot.saved(task);
        if (contract != null) {
            // Annual intensity/trend defaults are not evidence for a new arbitrary period.
            chapter6 = new JSONObject();
            String legalName = profile == null ? null : profile.getLegalName();
            metadata.put("entity_name", blank(legalName) ? contract.getString("companyName") : legalName);
            metadata.put("report_title", task.getTitle());
            metadata.put("template_name", contract.getString("templateName"));
            metadata.put("period_start", contract.getString("start")); metadata.put("period_end", contract.getString("end"));
            metadata.put("report_period", contract.getString("start") + "至" + contract.getString("end"));
            metadata.put("report_year", task.getReportYear());
            metadata.remove("report_month");
            if ("MONTH".equals(task.getPeriodType())) metadata.put("report_month", task.getReportMonth());
        }
        entity.putIfAbsent("short_name", "");
        entity.putIfAbsent("business_description", "");
        entity.putIfAbsent("carbon_department", "");

        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("render_contract_version", "calculation-source-v3");
        snapshot.put("entity_code", profile == null || blank(profile.getEntityCode()) ? "suning" : profile.getEntityCode());
        snapshot.put("period_grain", contract != null ? task.getPeriodType().toLowerCase(java.util.Locale.ROOT)
                : "MONTH".equalsIgnoreCase(task.getPeriodType()) ? "month" : "year");
        if (contract != null) snapshot.put("period_contract_version", 1);
        snapshot.put("metadata", metadata);
        snapshot.put("entity_profile", entity);
        snapshot.put("organization_boundary", boundary);
        snapshot.put("activity_prose", prose);
        snapshot.put("fuel_activity", fuels(draft.getFuels()));
        snapshot.put("electricity_activity", electricity(draft.getElectricity()));
        snapshot.put("monthly_fuel_activity", monthlyFuel == null ? List.of() : monthlyFuel);
        snapshot.put("monthly_electricity_activity", monthlyElectricity == null ? List.of() : monthlyElectricity);
        snapshot.put("heat_activity", heat(draft.getHeat()));
        snapshot.put("equipment", equipment(draft, profile));
        snapshot.put("workload", workload(draft.getWorkload()));
        snapshot.put("monitoring_devices", monitoring(draft.getMonitoring()));
        snapshot.put("report_tables", List.of());
        snapshot.put("images", ReportImageSlots.snapshotImages(draft.getImages(), draft.getDefaultImages()));
        com.alibaba.fastjson2.JSONObject source = com.ruoyi.carbon.report.source.ReportSourceSnapshot.saved(task);
        if (source != null) {
            attachSources((List<Map<String, Object>>) snapshot.get("fuel_activity"), draft.getFuels(), source);
            attachSources((List<Map<String, Object>>) snapshot.get("electricity_activity"), draft.getElectricity(), source);
            attachSources((List<Map<String, Object>>) snapshot.get("heat_activity"), draft.getHeat(), source);
            Map<String, Object> period = new LinkedHashMap<>();
            period.put("start", source.getString("cycleStart")); period.put("end", source.getString("cycleEnd"));
            period.put("partial", source.getBooleanValue("partialPeriod"));
            snapshot.put("source_period", period);
        }
        snapshot.put("chapter6", chapter6);
        snapshot.put("emission_boundary_notes", notes);
        putPriorComparisons(snapshot, task);
        if (factors != null && !factors.isEmpty())
        {
            snapshot.put("factors", factors);
        }
        return JSON.toJSONString(snapshot);
    }

    private static void attachSources(List<Map<String, Object>> items, List<ReportActivityRow> rows, JSONObject source)
    {
        for (int index = 0; index < rows.size(); index++) {
            ReportActivityRow row = rows.get(index);
            JSONObject line = com.ruoyi.carbon.report.source.ReportSourceSnapshot.line(source, row);
            if (line == null) throw new IllegalStateException("活动行缺少冻结来源");
            items.get(index).put("source_emission_tco2", line.getBigDecimal("carbonEmission"));
            items.get(index).put("factor_tco2_per_unit", line.getBigDecimal("factorTco2PerUnit"));
            items.get(index).put("data_origin", row.getDataOrigin());
            items.get(index).put("override_reason", row.getOverrideReason() == null ? "" : row.getOverrideReason());
        }
    }

    private static List<Map<String, Object>> fuels(List<ReportActivityRow> rows)
    {
        List<Map<String, Object>> list = new ArrayList<>();
        for (ReportActivityRow row : rows)
        {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("fuel_type", row.getFuelType());
            item.put("facility", nvl(row.getFacility()));
            item.put("quantity", row.getNormalizedValue() == null ? 0 : row.getNormalizedValue());
            item.put("unit", nvl(row.getNormalizedUnit()));
            item.put("source_name", nvl(row.getSourceName()));
            list.add(item);
        }
        return list;
    }

    private static List<Map<String, Object>> electricity(List<ReportActivityRow> rows)
    {
        List<Map<String, Object>> list = new ArrayList<>();
        for (ReportActivityRow row : rows)
        {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("scope", row.getScope() == null ? "purchased-electricity" : row.getScope());
            item.put("quantity_mwh", row.getNormalizedValue() == null ? 0 : row.getNormalizedValue());
            item.put("source_name", nvl(row.getSourceName()));
            list.add(item);
        }
        return list;
    }

    private static List<Map<String, Object>> heat(List<ReportActivityRow> rows)
    {
        List<Map<String, Object>> list = new ArrayList<>();
        for (ReportActivityRow row : rows)
        {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("site", row.getSite() == null ? nvl(row.getFacility()) : row.getSite());
            item.put("quantity_gj", row.getNormalizedValue() == null ? 0 : row.getNormalizedValue());
            if (row.getHeatingAreaM2() != null)
            {
                item.put("heating_area_m2", row.getHeatingAreaM2());
            }
            if (row.getHeatCoefficient() != null)
            {
                item.put("heat_coefficient", row.getHeatCoefficient());
            }
            item.put("source_name", nvl(row.getSourceName()));
            list.add(item);
        }
        return list;
    }

    private static List<Map<String, Object>> equipment(ReportDraft draft, ReportDeptProfile profile)
    {
        if (draft.getEquipment() != null && !draft.getEquipment().isEmpty())
        {
            return equipmentFromRows(draft.getEquipment());
        }
        if (profile != null && !blank(profile.getDefaultEquipmentJson()))
        {
            return equipmentFromJson(profile.getDefaultEquipmentJson());
        }
        return List.of();
    }

    private static List<Map<String, Object>> equipmentFromRows(List<ReportEquipment> rows)
    {
        List<Map<String, Object>> list = new ArrayList<>();
        for (ReportEquipment row : rows)
        {
            list.add(equipmentItem(
                    nvl(row.getName()),
                    nvl(row.getCategory()),
                    row.getQuantity(),
                    nvl(row.getUnit()),
                    nvl(row.getModel()),
                    nvl(row.getEnergyType()),
                    nvl(row.getRemark())));
        }
        return list;
    }

    private static List<Map<String, Object>> equipmentFromJson(String json)
    {
        JSONArray items;
        try
        {
            items = JSON.parseArray(json);
        }
        catch (Exception ex)
        {
            return List.of();
        }
        if (items == null || items.isEmpty())
        {
            return List.of();
        }
        List<Map<String, Object>> list = new ArrayList<>();
        for (int i = 0; i < items.size(); i++)
        {
            JSONObject item = items.getJSONObject(i);
            if (item == null)
            {
                continue;
            }
            String energy = item.getString("energy_type");
            if (blank(energy))
            {
                energy = item.getString("energyType");
            }
            list.add(equipmentItem(
                    nvl(item.getString("name")),
                    nvl(item.getString("category")),
                    item.get("quantity"),
                    nvl(item.getString("unit")),
                    nvl(item.getString("model")),
                    nvl(energy),
                    nvl(item.getString("remark"))));
        }
        return list;
    }

    private static Map<String, Object> equipmentItem(String name, String category, Object quantity,
            String unit, String model, String energyType, String remark)
    {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("name", name);
        item.put("category", category);
        item.put("quantity", quantity);
        item.put("unit", unit);
        item.put("model", model);
        item.put("energy_type", energyType);
        item.put("remark", remark);
        return item;
    }

    private static List<Map<String, Object>> workload(List<ReportWorkload> rows)
    {
        List<Map<String, Object>> list = new ArrayList<>();
        if (rows == null)
        {
            return list;
        }
        for (ReportWorkload row : rows)
        {
            if (row.getQuantity() == null || row.getQuantity().signum() <= 0)
            {
                continue;
            }
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", nvl(row.getName()));
            item.put("quantity", row.getQuantity());
            item.put("unit", nvl(row.getUnit()));
            list.add(item);
        }
        return list;
    }

    private static List<Map<String, Object>> monitoring(List<ReportMonitoringDevice> rows)
    {
        List<Map<String, Object>> list = new ArrayList<>();
        if (rows == null)
        {
            return list;
        }
        for (ReportMonitoringDevice row : rows)
        {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("name", nvl(row.getName()));
            item.put("model", nvl(row.getModel()));
            item.put("accuracy", nvl(row.getAccuracy()));
            item.put("measurement_range", nvl(row.getMeasurementRange()));
            item.put("location", nvl(row.getLocation()));
            item.put("calibration_frequency", nvl(row.getCalibrationFrequency()));
            list.add(item);
        }
        return list;
    }

    private static void putPriorComparisons(Map<String, Object> snapshot, ReportTask task)
    {
        if (ReportPeriodSnapshot.enabled(task) && "RANGE".equals(task.getPeriodType())) return;
        if (task.getPriorYearJson() == null || task.getPriorYearJson().isBlank())
        {
            return;
        }
        JSONObject prior = parse(task.getPriorYearJson());
        if ("MONTH".equalsIgnoreCase(task.getPeriodType()))
        {
            putIfHasTotal(snapshot, "prior_year", rendererPrior(task, prior.getJSONObject("yoy")));
            putIfHasTotal(snapshot, "prior_month", rendererPrior(task, prior.getJSONObject("mom")));
            return;
        }
        putIfHasTotal(snapshot, "prior_year", rendererPrior(task, prior));
    }

    private static JSONObject rendererPrior(ReportTask task, JSONObject prior) {
        if (prior == null || !ReportPeriodSnapshot.enabled(task)) return prior;
        JSONObject value = new JSONObject(prior);
        JSONObject evidence = value.getJSONObject("_comparison"); value.remove("_comparison");
        if (evidence != null) {
            value.put("period_start", evidence.getString("start")); value.put("period_end", evidence.getString("end"));
            value.put("source_label", "TASK".equals(evidence.getString("mode"))
                    ? "核算任务" + evidence.getLong("taskId") : "手工填报");
        }
        return value;
    }

    private static void putIfHasTotal(Map<String, Object> snapshot, String key, JSONObject prior)
    {
        if (prior != null && prior.get("total_emissions_tco2") != null)
        {
            snapshot.put(key, prior);
        }
    }

    private static JSONObject parse(String json)
    {
        if (json == null || json.isBlank())
        {
            return new JSONObject();
        }
        return JSON.parseObject(json);
    }

    private static boolean blank(String value)
    {
        return value == null || value.isBlank();
    }

    private static void fillIfBlank(JSONObject target, String key, String fallback)
    {
        if (blank(target.getString(key)) && !blank(fallback))
        {
            target.put(key, fallback);
        }
    }

    private static String nvl(String value)
    {
        return value == null ? "" : value;
    }
}
