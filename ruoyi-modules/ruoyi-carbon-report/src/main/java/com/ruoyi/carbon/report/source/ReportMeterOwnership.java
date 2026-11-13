package com.ruoyi.carbon.report.source;

import java.util.Objects;
import java.util.Set;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;

/** One ownership decision used by prefill and comparison scope. Never uses a station label as a company. */
public final class ReportMeterOwnership {
    public enum Decision { ACCEPT, MISSING, OTHER, INVALID, CONFLICT }
    private ReportMeterOwnership() { }
    public static Decision decide(Long company, Set<String> legacyAliases, CalculationNodeDataRow row) {
        String legacy = row.getEnergyAllocation() == null ? "" : row.getEnergyAllocation().trim();
        boolean legacyMatches = legacyAliases.contains(legacy);
        if (row.getAttributionDeptId() == null)
            return legacy.isEmpty() ? Decision.MISSING : legacyMatches ? Decision.ACCEPT : Decision.OTHER;
        // A broken new identity must not silently fall back to an unrelated old label.
        if (company == null || row.getAttributionCompanyDeptId() == null) return Decision.INVALID;
        boolean structuredMatches = Objects.equals(company, row.getAttributionCompanyDeptId());
        if (!legacy.isEmpty() && structuredMatches != legacyMatches) return Decision.CONFLICT;
        return structuredMatches ? Decision.ACCEPT : Decision.OTHER;
    }
}
