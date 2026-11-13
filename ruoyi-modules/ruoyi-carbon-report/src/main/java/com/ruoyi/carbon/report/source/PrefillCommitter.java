package com.ruoyi.carbon.report.source;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.PrefillLine;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.generation.SnapshotHasher;

/**
 * Applies auto-prefill onto a report task without recomputing emissions.
 */
public class PrefillCommitter
{
    public void apply(ReportTask task, PrefillResult result, Long calculationTemplateId)
    {
        task.setCalculationTemplateId(calculationTemplateId);
        task.setSourceHash(hash(calculationTemplateId, result));
        task.setVersion(task.getVersion() == null ? 1 : task.getVersion() + 1);
    }

    public List<ReportActivityRow> toFuelRows(ReportTask task, PrefillResult result)
    {
        List<ReportActivityRow> rows = new ArrayList<>();
        int order = 0;
        for (PrefillLine line : result.getFuels())
        {
            rows.add(toRow(task, line, "fuel", order++));
        }
        return rows;
    }

    public List<ReportActivityRow> toElectricityRows(ReportTask task, PrefillResult result)
    {
        List<ReportActivityRow> rows = new ArrayList<>();
        int order = 0;
        for (PrefillLine line : result.getElectricity())
        {
            ReportActivityRow row = toRow(task, line, "electricity", order++);
            row.setScope("purchased-electricity");
            rows.add(row);
        }
        return rows;
    }

    public List<ReportActivityRow> toHeatRows(ReportTask task, PrefillResult result)
    {
        List<ReportActivityRow> rows = new ArrayList<>();
        int order = 0;
        for (PrefillLine line : result.getHeat())
        {
            ReportActivityRow row = toRow(task, line, "heat", order++);
            row.setSite(line.getFacility());
            rows.add(row);
        }
        return rows;
    }

    /** Refresh AUTO rows while preserving explicitly overridden input and its original frozen factor. */
    public List<ReportActivityRow> protectOverrides(ReportTask task, List<ReportActivityRow> existing,
            List<ReportActivityRow> incoming, List<PrefillLine> lines)
    {
        if (existing == null || existing.isEmpty()) return incoming;
        List<ReportActivityRow> merged = new ArrayList<>(incoming);
        com.alibaba.fastjson2.JSONObject frozen = ReportSourceSnapshot.saved(task);
        for (ReportActivityRow old : existing) {
            boolean heatInput = old.getHeatingAreaM2() != null || old.getHeatCoefficient() != null;
            if ("AUTO".equals(old.getDataOrigin()) && !heatInput) continue;
            int match = -1;
            for (int i = 0; i < merged.size(); i++) {
                ReportActivityRow next = merged.get(i);
                if (old.getSourceId() != null && java.util.Objects.equals(old.getSourceTable(), next.getSourceTable())
                        && old.getSourceId().equals(next.getSourceId())) { match = i; break; }
            }
            com.alibaba.fastjson2.JSONObject original = frozen == null ? null : ReportSourceSnapshot.line(frozen, old);
            BigDecimal factor = match < 0 ? null : lines.get(match).getFactorTco2PerUnit();
            BigDecimal previous = original == null ? null : original.getBigDecimal("factorTco2PerUnit");
            if ("AUTO".equals(old.getDataOrigin()) && heatInput && match >= 0 && previous != null && factor != null
                    && previous.compareTo(factor) == 0
                    && java.util.Objects.equals(old.getNormalizedUnit(), merged.get(match).getNormalizedUnit())) {
                merged.get(match).setHeatingAreaM2(old.getHeatingAreaM2());
                merged.get(match).setHeatCoefficient(old.getHeatCoefficient());
                continue;
            }
            if (!"OVERRIDE".equals(old.getDataOrigin()) || match < 0 || previous == null || factor == null
                    || previous.compareTo(factor) != 0
                    || !java.util.Objects.equals(old.getNormalizedUnit(), merged.get(match).getNormalizedUnit()))
                throw new com.ruoyi.common.core.exception.ServiceException(
                    "报告含手工活动行或来源/因子已变化的覆盖值，不能直接重新带入；请保留本报告并另建草稿核对，原填报未改动", 409);
            ReportActivityRow next = merged.get(match);
            ReportActivityRow kept = com.alibaba.fastjson2.JSON.parseObject(
                    com.alibaba.fastjson2.JSON.toJSONString(old), ReportActivityRow.class);
            kept.setSourceHash(next.getSourceHash()); kept.setSourceValue(next.getSourceValue());
            kept.setSourceUnit(next.getSourceUnit()); kept.setSortOrder(next.getSortOrder());
            merged.set(match, kept);
        }
        return merged;
    }

    public void overrideNormalized(ReportActivityRow row, BigDecimal value, String reason)
    {
        row.setNormalizedValue(value);
        row.setQuantity(value);
        row.setDataOrigin("OVERRIDE");
        row.setOverrideReason(reason);
    }

    public static String hash(Long calculationTemplateId, PrefillResult result)
    {
        StringBuilder builder = new StringBuilder();
        builder.append(calculationTemplateId).append('|');
        result.getFuels().forEach(line -> builder.append(line.getSourceHash()).append(','));
        result.getElectricity().forEach(line -> builder.append(line.getSourceHash()).append(','));
        result.getHeat().forEach(line -> builder.append(line.getSourceHash()).append(','));
        return SnapshotHasher.sha256(builder.toString());
    }

    private static ReportActivityRow toRow(ReportTask task, PrefillLine line, String kind, int order)
    {
        ReportActivityRow row = new ReportActivityRow();
        row.setDeptId(task.getDeptId());
        row.setReportId(task.getId());
        row.setKind(kind);
        row.setFuelType(line.getFuelType());
        row.setFacility(line.getFacility());
        row.setQuantity(line.getNormalizedValue());
        row.setUnit(line.getNormalizedUnit());
        row.setSourceName(line.getFacility());
        row.setDataOrigin(line.getDataOrigin() == null ? "AUTO" : line.getDataOrigin());
        row.setSourceTable(line.getSourceTable());
        row.setSourceId(line.getSourceId());
        row.setSourceValue(line.getSourceValue());
        row.setSourceUnit(line.getSourceUnit());
        row.setNormalizedValue(line.getNormalizedValue());
        row.setNormalizedUnit(line.getNormalizedUnit());
        row.setHeatingAreaM2(line.getHeatingAreaM2());
        row.setHeatCoefficient(line.getHeatCoefficient());
        row.setSourceHash(line.getSourceHash());
        row.setOverrideReason(line.getOverrideReason());
        row.setSortOrder(order);
        return row;
    }
}
