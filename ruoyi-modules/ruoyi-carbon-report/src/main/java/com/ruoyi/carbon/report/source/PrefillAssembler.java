package com.ruoyi.carbon.report.source;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.dto.PrefillLine;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;

/**
 * Builds report activity lines from calculation snapshots. Does not recompute emissions.
 */
public class PrefillAssembler
{
    public static final int SUCCESS_STATUS = 2;

    private final ReportUnitConverter converter;

    public PrefillAssembler(ReportUnitConverter converter)
    {
        this.converter = converter;
    }

    public List<CalculationCandidate> selectable(List<CalculationCandidate> all)
    {
        return all.stream().filter(CalculationCandidate::isSuccess).collect(Collectors.toList());
    }

    public PrefillResult assemble(String energyAllocation, List<CalculationNodeDataRow> rows)
    {
        return assembleAllocations(energyAllocation == null || energyAllocation.isBlank()
                ? Set.of() : Set.of(energyAllocation.trim()), rows);
    }

    public PrefillResult assembleAllocations(Set<String> energyAllocations, List<CalculationNodeDataRow> rows)
    {
        return assembleForCompany(null, energyAllocations, rows);
    }

    public PrefillResult assembleForCompany(Long companyDeptId, Set<String> energyAllocations,
            List<CalculationNodeDataRow> rows)
    {
        PrefillResult result = new PrefillResult();
        Map<String, Integer> missingAllocation = new LinkedHashMap<>();
        Map<String, Integer> otherAllocation = new LinkedHashMap<>();
        Set<String> seen = new LinkedHashSet<>();
        for (CalculationNodeDataRow row : rows)
        {
            String sourceCode = row.getEmissionSubcategory();
            ReportMeterOwnership.Decision ownership = ReportMeterOwnership.decide(companyDeptId, energyAllocations, row);
            if (ownership == ReportMeterOwnership.Decision.MISSING) {
                count(missingAllocation, sourceCode); continue;
            }
            if (ownership == ReportMeterOwnership.Decision.OTHER) {
                count(otherAllocation, sourceCode); continue;
            }
            if (ownership != ReportMeterOwnership.Decision.ACCEPT) {
                String reason = ownership == ReportMeterOwnership.Decision.INVALID
                    ? "归属部门无效、停用或无法对应已登记公司"
                    : "归属部门与旧归属字段冲突";
                ReportSourceSnapshot.issue(result, "ALLOCATION_" + ownership, row.getId(),
                    "采集点" + row.getCollectionPointId() + "（" + row.getFacilityName() + "）" + reason
                    + "；部门ID=" + row.getAttributionDeptId() + "，公司ID=" + row.getAttributionCompanyDeptId()
                    + "，旧归属=" + String.valueOf(row.getEnergyAllocation()) + "；该行未带入", true);
                continue;
            }
            if (Integer.valueOf(2).equals(row.getDataStatus())) {
                ReportSourceSnapshot.issue(result, "SOURCE_NO_DATA", row.getId(), "核算明细" + row.getId() + "没有采集数据，不能作为真实零值带入", true);
                continue;
            }
            String code = ActivityClassifier.canonical(sourceCode, row.getMeasurementUnit());
            String bucket = ActivityClassifier.bucket(code);
            if ("fuel".equals(bucket) && ReportUnitConverter.reportFuelType(code) == null)
            {
                addGap(result, seen, "报告只收录天然气、汽油、柴油：" + code);
                continue;
            }
            if (!"fuel".equals(bucket) && !"electricity".equals(bucket) && !"heat".equals(bucket))
            {
                if (code != null && code.regionMatches(true, 0, "WT_", 0, 3))
                {
                    addGap(result, seen, "报告不包含该类排放：" + code);
                }
                else
                {
                    addGap(result, seen, "无法归类：" + code);
                }
                continue;
            }
            PrefillLine line = new PrefillLine();
            line.setSourceTable("emission_collection_node_data");
            line.setSourceId(row.getId() == null ? null : String.valueOf(row.getId()));
            line.setSubcategory(code);
            line.setFacility(row.getFacilityName());
            line.setCarbonEmission(row.preferredCarbonValue());
            line.setDataOrigin("AUTO");
            ReportUnitConverter.Conversion conversion = converter.convert(
                    code, row.preferredEnergyValue(), row.getMeasurementUnit());
            line.setSourceValue(row.preferredEnergyValue());
            line.setSourceUnit(row.getMeasurementUnit());
            if (!conversion.ok)
            {
                addGap(result, seen, "缺少单位换算：" + code + " " + row.getMeasurementUnit());
                continue;
            }
            line.setNormalizedValue(conversion.normalizedValue);
            line.setNormalizedUnit(conversion.normalizedUnit);
            ReportSourceSnapshot.inspectLine(result, line, row);
            line.setSourceHash(hash(com.alibaba.fastjson2.JSON.toJSONString(row), conversion.normalizedValue, conversion.normalizedUnit));
            if ("fuel".equals(bucket))
            {
                line.setFuelType(ReportUnitConverter.reportFuelType(code));
                result.getFuels().add(line);
            }
            else if ("electricity".equals(bucket))
            {
                result.getElectricity().add(line);
            }
            else
            {
                applyHeatArea(line, conversion);
                result.getHeat().add(line);
            }
        }
        if (!missingAllocation.isEmpty()) ReportSourceSnapshot.issue(result, "ALLOCATION_MISSING", null,
                "表计归属待确认，已跳过" + missingAllocation.values().stream().mapToInt(Integer::intValue).sum() + "行：" + String.join("、", missingAllocation.keySet()), true);
        addAllocationGap(result, "表计属于其他部门，已跳过 ", otherAllocation);
        return result;
    }

    private static void count(Map<String, Integer> counts, String code)
    {
        String key = code == null || code.isBlank() ? "未分类" : code;
        counts.merge(key, 1, Integer::sum);
    }

    private static void addGap(PrefillResult result, Set<String> seen, String message)
    {
        if (seen.add(message))
        {
            ReportSourceSnapshot.issue(result, "SOURCE_UNSUPPORTED", null, message, true);
        }
    }

    private static void addAllocationGap(PrefillResult result, String prefix, Map<String, Integer> counts)
    {
        if (counts.isEmpty())
        {
            return;
        }
        int total = 0;
        for (int count : counts.values())
        {
            total += count;
        }
        result.getGaps().add(prefix + total + " 行：" + String.join("、", counts.keySet()));
    }

    public BigDecimal sumEmissions(List<CalculationNodeDataRow> rows)
    {
        return rows.stream()
                .map(CalculationNodeDataRow::preferredCarbonValue)
                .filter(v -> v != null)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private static void applyHeatArea(PrefillLine line, ReportUnitConverter.Conversion conversion)
    {
        if (!"PH_HA".equalsIgnoreCase(line.getSubcategory()) || !ReportUnitConverter.isAreaUnit(conversion.sourceUnit))
        {
            return;
        }
        line.setHeatingAreaM2(conversion.sourceValue);
        line.setHeatCoefficient(conversion.factor);
    }

    private static String hash(Object... parts)
    {
        try
        {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            String joined = java.util.Arrays.stream(parts).map(String::valueOf).collect(Collectors.joining("|"));
            return HexFormat.of().formatHex(digest.digest(joined.getBytes(StandardCharsets.UTF_8)));
        }
        catch (Exception ex)
        {
            throw new IllegalStateException(ex);
        }
    }

    public static List<PrefillLine> copyWithoutTouchingSource(List<PrefillLine> lines, BigDecimal overrideValue, String reason)
    {
        List<PrefillLine> copied = new ArrayList<>();
        for (PrefillLine line : lines)
        {
            PrefillLine next = line.copy();
            if (overrideValue != null)
            {
                next.setNormalizedValue(overrideValue);
                next.setDataOrigin("OVERRIDE");
                next.setOverrideReason(reason);
            }
            copied.add(next);
        }
        return copied;
    }
}
