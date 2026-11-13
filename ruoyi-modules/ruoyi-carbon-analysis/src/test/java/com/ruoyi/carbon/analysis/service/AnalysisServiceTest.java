package com.ruoyi.carbon.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import java.time.LocalDate;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;

class AnalysisServiceTest
{
    @Test
    void monthUsesCompleteBoundary()
    {
        assertEquals(LocalDate.of(2025, 1, 1), AnalysisService.parseDate("2025-01", "开始日期", false));
        assertEquals(LocalDate.of(2025, 2, 28), AnalysisService.parseDate("2025-02", "结束日期", true));
    }

    @Test
    void yearUsesCompleteBoundary()
    {
        assertEquals(LocalDate.of(2025, 1, 1), AnalysisService.parseDate("2025", "开始日期", false));
        assertEquals(LocalDate.of(2025, 12, 31), AnalysisService.parseDate("2025", "结束日期", true));
    }

    @Test
    void fullDateAndTimestampKeepExactDate()
    {
        assertEquals(LocalDate.of(2025, 3, 6), AnalysisService.parseDate("2025-03-06", "开始日期", false));
        assertEquals(LocalDate.of(2025, 3, 6), AnalysisService.parseDate("2025-03-06 12:30:00", "结束日期", true));
    }

    @Test
    void invalidDateReturnsBusinessError()
    {
        ServiceException error = assertThrows(ServiceException.class,
                () -> AnalysisService.parseDate("2025-1", "开始日期", false));
        assertEquals("开始日期格式不正确，请使用 yyyy、yyyy-MM 或 yyyy-MM-dd", error.getMessage());
    }

    @Test
    void nonZeroDirectFactsReplaceBrokenZeroSummary()
    {
        AnalysisFact summary = fact(10L, "0");
        AnalysisFact direct = fact(10L, "12.5");
        List<AnalysisFact> merged = AnalysisService.mergeSummaryAndDirectFacts(List.of(summary), List.of(direct));
        assertEquals(1, merged.size());
        assertEquals(new BigDecimal("12.5"), merged.get(0).getCarbonValue());
    }

    @Test
    void validSummaryRemainsAuthoritative()
    {
        AnalysisFact summary = fact(10L, "15");
        AnalysisFact direct = fact(10L, "12.5");
        List<AnalysisFact> merged = AnalysisService.mergeSummaryAndDirectFacts(List.of(summary), List.of(direct));
        assertEquals(1, merged.size());
        assertEquals(new BigDecimal("15"), merged.get(0).getCarbonValue());
    }

    private AnalysisFact fact(Long templateId, String carbon)
    {
        AnalysisFact fact = new AnalysisFact();
        fact.setTemplateId(templateId);
        fact.setCarbonValue(new BigDecimal(carbon));
        return fact;
    }
}
