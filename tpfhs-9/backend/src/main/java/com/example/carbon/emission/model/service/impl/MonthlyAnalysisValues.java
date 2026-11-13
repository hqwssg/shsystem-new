package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import java.math.BigDecimal;

/** One selection rule for cards, charts, comparisons, details and export. */
public final class MonthlyAnalysisValues {
    private MonthlyAnalysisValues() { }
    public record Pair(BigDecimal energy, BigDecimal carbon) { }
    public static Pair select(MonthlyCollectionNodeData row, String mode) {
        if (row == null || Integer.valueOf(2).equals(row.getDataStatus())) return new Pair(null, null);
        String basis = mode;
        if ("ADOPTED".equals(mode)) {
            basis = Integer.valueOf(1).equals(row.getTotalEmissionCalcMethod()) ? "ADJUSTED"
                    : Integer.valueOf(2).equals(row.getTotalEmissionCalcMethod()) ? "RAW" : "UNKNOWN";
        }
        return switch (basis) {
            case "RAW" -> new Pair(row.getEnergyMeasurementValue(), row.getCarbonEmission());
            case "ADJUSTED" -> new Pair(row.getAdjustedEnergyValue(), row.getAdjustedCarbonEmission());
            default -> new Pair(null, null);
        };
    }
    public static BigDecimal difference(BigDecimal adjusted, BigDecimal raw) {
        return adjusted == null || raw == null ? null : adjusted.subtract(raw);
    }
}
