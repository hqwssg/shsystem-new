package com.ruoyi.carbon.report.source;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.PrefillLine;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;

/** Immutable source evidence in existing report metadata, never accepted from basic-form input. */
public final class ReportSourceSnapshot
{
    public static final String KEY = "_source_snapshot";
    private ReportSourceSnapshot() { }

    public static void issue(PrefillResult result, String code, Long id, String message, boolean blocking)
    {
        result.getIssues().add(Map.of("code", code, "sourceId", id == null ? "" : id.toString(),
                "message", message, "blocking", blocking));
        if (!result.getGaps().contains(message)) result.getGaps().add(message);
    }

    public static BigDecimal factor(String category, BigDecimal value, String unit)
    {
        if (value == null || value.signum() < 0 || unit == null) return null;
        String[] parts = unit.replace(" ", "").replace("₂", "2").split("/");
        if (parts.length != 2) return null;
        String numerator = parts[0].toLowerCase(java.util.Locale.ROOT);
        BigDecimal mass = switch (numerator) {
            case "tco2", "tco2e", "t" -> BigDecimal.ONE;
            case "kgco2", "kgco2e", "kg" -> new BigDecimal("0.001");
            default -> null;
        };
        if (mass == null || ReportUnitConverter.isAreaUnit(parts[1])) return null;
        ReportUnitConverter.Conversion denominator = new ReportUnitConverter().convert(category, BigDecimal.ONE, parts[1]);
        if (!denominator.ok || denominator.normalizedValue.signum() == 0) return null;
        return value.multiply(mass).divide(denominator.normalizedValue, 15, RoundingMode.HALF_UP);
    }

    public static void inspectLine(PrefillResult result, PrefillLine line, CalculationNodeDataRow row)
    {
        line.setValueBasis(row.getAdjustedEnergyValue() == null ? "RAW" : "ADJUSTED");
        line.setFactorTco2PerUnit(factor(line.getSubcategory(), row.getCarbonEmissionFactor(), row.getCarbonEmissionFactorUnit()));
        if (!Integer.valueOf(1).equals(row.getDataStatus()))
            issue(result, "SOURCE_QUALITY", row.getId(), "核算明细" + row.getId() + "数据质量待核对（状态"
                    + row.getDataStatus() + "）：" + String.valueOf(row.getDataMissingDescription()), true);
        if (line.getCarbonEmission() == null || line.getFactorTco2PerUnit() == null
                || row.getCarbonEmissionUnit() == null || !row.getCarbonEmissionUnit().replace("₂", "2").matches("(?i)tCO2e?"))
            issue(result, "SOURCE_FACTOR_MISSING", row.getId(), "核算明细" + row.getId() + "缺少完整的排放量、因子或单位快照，请重新核算", true);
        else if (line.getNormalizedValue().multiply(line.getFactorTco2PerUnit()).subtract(line.getCarbonEmission()).abs().compareTo(new BigDecimal("0.000001")) > 0)
            issue(result, "SOURCE_EMISSION_MISMATCH", row.getId(), "核算明细" + row.getId() + "活动量、因子与排放量不一致，请核对后重新核算", true);
        // Detect the observed historical fallback bug, while retaining the original task evidence.
        BigDecimal template = factor(line.getSubcategory(), row.getTemplateFactor(), row.getTemplateFactorUnit());
        if (row.getConfiguredFactor() == null && row.getCarbonEmissionFactor() != null && row.getTemplateFactor() != null
                && row.getCarbonEmissionFactor().compareTo(row.getTemplateFactor()) == 0
                && line.getFactorTco2PerUnit() != null && template != null
                && line.getFactorTco2PerUnit().compareTo(template) != 0)
            issue(result, "LEGACY_FACTOR_UNIT_CONFLICT", row.getId(), "核算明细" + row.getId()
                    + "存在历史因子数值与单位混配（" + row.getCarbonEmissionFactorUnit() + " / " + row.getTemplateFactorUnit()
                    + "），须修复后新建核算任务；旧结果保留", true);
    }

    public static JSONObject metadata(ReportTask task)
    {
        return task.getMetadataJson() == null || task.getMetadataJson().isBlank() ? new JSONObject() : JSON.parseObject(task.getMetadataJson());
    }
    public static JSONObject saved(ReportTask task) { return metadata(task).getJSONObject(KEY); }
    public static void freeze(ReportTask task, PrefillResult result)
    {
        JSONObject metadata = metadata(task);
        metadata.put(KEY, JSON.toJSON(result)); task.setMetadataJson(metadata.toJSONString());
    }
    public static List<String> problems(ReportDraft draft)
    {
        List<String> problems = new ArrayList<>();
        if (draft == null || draft.getTask() == null) return problems;
        JSONObject source = saved(draft.getTask());
        if (source == null) {
            if (draft.getTask().getCalculationTemplateId() != null) problems.add("该报告尚未冻结核算来源，请重新预览并带入；原有填报将保留");
            return problems;
        }
        PrefillResult result = source.toJavaObject(PrefillResult.class);
        result.getIssues().stream().filter(i -> Boolean.TRUE.equals(i.get("blocking")))
                .forEach(i -> problems.add(String.valueOf(i.get("message"))));
        List<ReportActivityRow> rows = new ArrayList<>(); rows.addAll(draft.getFuels()); rows.addAll(draft.getElectricity()); rows.addAll(draft.getHeat());
        if (rows.size() != result.getLineCount()) problems.add("活动行数量与冻结核算来源不一致，请重新带入；不得静默遗漏核算明细");
        for (ReportActivityRow row : rows) {
            JSONObject line = line(source, row);
            if (line == null || line.getBigDecimal("factorTco2PerUnit") == null)
                problems.add("活动行缺少冻结的核算因子，请重新带入：" + row.getSourceName());
            else if (!"OVERRIDE".equals(row.getDataOrigin()) && (row.getNormalizedValue() == null
                    || row.getNormalizedValue().compareTo(line.getBigDecimal("normalizedValue")) != 0
                    || !java.util.Objects.equals(row.getNormalizedUnit(), line.getString("normalizedUnit"))))
                problems.add("活动行与冻结来源不一致，请重新带入或使用有理由的报告覆盖：" + row.getSourceName());
            else if ("OVERRIDE".equals(row.getDataOrigin()) && (row.getOverrideReason() == null || row.getOverrideReason().isBlank()))
                problems.add("报告覆盖必须填写原因：" + row.getSourceName());
        }
        return problems;
    }
    public static JSONObject line(JSONObject source, ReportActivityRow row)
    {
        for (String bucket : List.of("fuels", "electricity", "heat"))
            if (source.getJSONArray(bucket) != null) for (Object value : source.getJSONArray(bucket)) {
                JSONObject line = (JSONObject) value;
                if (java.util.Objects.equals(row.getSourceId(), line.getString("sourceId"))
                        && java.util.Objects.equals(row.getSourceHash(), line.getString("sourceHash"))) return line;
            }
        return null;
    }
}
