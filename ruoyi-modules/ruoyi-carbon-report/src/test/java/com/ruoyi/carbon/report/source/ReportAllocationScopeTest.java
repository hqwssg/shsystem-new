package com.ruoyi.carbon.report.source;

import java.util.List;
import java.util.Set;
import com.ruoyi.carbon.report.domain.ReportSubjectOption;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReportAllocationScopeTest
{
    private ReportSubjectOption company(long id, String name, String code)
    {
        ReportSubjectOption row = new ReportSubjectOption();
        row.setDeptId(id); row.setDeptName(name); row.setEnergyAllocation(code);
        return row;
    }

    @Test
    void sharedHeadOfficeAndBranchCodeDoesNotWidenMeterScope()
    {
        ReportSubjectOption branch = company(3020L, "肃宁分公司", "suring");
        ReportSubjectOption head = company(3000L, "总公司", "suring");
        assertTrue(ReportAllocationScope.accepted(3020L, branch, branch, List.of(branch, head)).isEmpty());
    }

    @Test
    void uniqueRegisteredIdentityAcceptsOnlyExactCodeAndName()
    {
        ReportSubjectOption company = company(3030L, "机辆分公司", "jilong");
        assertEquals(Set.of("jilong", "机辆分公司"),
                ReportAllocationScope.accepted(3030L, company, company, List.of(company)));
    }

    @Test
    void changedMappingDoesNotExpandHistoricalReportBoundary()
    {
        ReportSubjectOption saved = company(3030L, "机辆分公司", "jilong");
        ReportSubjectOption current = company(3030L, "新公司名称", "replacement");
        assertEquals(Set.of("jilong"),
                ReportAllocationScope.accepted(3030L, saved, current, List.of(current)));
    }
}
