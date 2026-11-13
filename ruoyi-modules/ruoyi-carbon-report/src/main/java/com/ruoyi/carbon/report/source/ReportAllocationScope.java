package com.ruoyi.carbon.report.source;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportSubjectOption;

/** Resolve a registered company's exact display name alongside its saved allocation code. */
public final class ReportAllocationScope
{
    private ReportAllocationScope() { }

    public static Set<String> accepted(Long deptId, ReportDeptSubject saved,
            ReportDeptSubject current, List<ReportSubjectOption> registeredCompanies)
    {
        Set<String> result = new LinkedHashSet<>();
        String code = clean(saved == null ? null : saved.getEnergyAllocation());
        if (code.isEmpty()) return result;
        if (registeredCompanies != null && registeredCompanies.stream().anyMatch(row ->
                !java.util.Objects.equals(deptId, row.getDeptId()) && code.equals(clean(row.getEnergyAllocation()))))
            return result; // An allocation shared by companies is not a unique identity.
        result.add(code);
        // Do not use a changed mapping to broaden an existing report's saved boundary.
        if (deptId == null || current == null || !code.equals(clean(current.getEnergyAllocation()))
                || registeredCompanies == null) return result;
        List<ReportSubjectOption> own = registeredCompanies.stream()
                .filter(row -> deptId.equals(row.getDeptId())).toList();
        if (own.size() != 1 || !code.equals(clean(own.get(0).getEnergyAllocation()))) return result;
        String name = clean(own.get(0).getDeptName());
        if (name.isEmpty()) return result;
        boolean ambiguous = registeredCompanies.stream().anyMatch(row -> !deptId.equals(row.getDeptId())
                && (name.equals(clean(row.getDeptName())) || name.equals(clean(row.getEnergyAllocation()))));
        if (!ambiguous) result.add(name);
        return result;
    }

    private static String clean(String value) { return value == null ? "" : value.trim(); }
}
