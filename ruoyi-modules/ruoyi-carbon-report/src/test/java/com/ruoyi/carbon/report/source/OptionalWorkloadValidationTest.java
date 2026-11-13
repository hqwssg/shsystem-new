package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.*;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.report.domain.ReportActivityRow;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.ReportWorkload;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;

class OptionalWorkloadValidationTest
{
    private ReportDraft draft() {
        ReportDraft draft = new ReportDraft();
        ReportTask task = new ReportTask();task.setId(1L);task.setDeptId(3030L);
        draft.setTask(task);
        draft.getElectricity().add(new ReportActivityRow());
        return draft;
    }

    @Test void emptyWorkloadIsAnAdvisoryAndIsNotReplacedWithZero() {
        ReportDraft draft = draft();
        var result = ReportValidator.validate(draft);
        assertEquals(true, result.get("ok"));
        assertEquals(true, result.get("missingWorkload"));
        assertEquals(List.of(), result.get("mustFix"));
        assertTrue(result.get("shouldConfirm").toString().contains("不计算排放强度"));
        assertTrue(draft.getWorkload().isEmpty());
    }

    @Test void suppliedWorkloadRemainsUntouchedAndNeedsNoMissingAdvisory() {
        ReportDraft draft = draft();
        ReportWorkload workload = new ReportWorkload();
        workload.setName("合成测试周转量");workload.setQuantity(new BigDecimal("100"));workload.setUnit("测试单位");
        draft.getWorkload().add(workload);draft.setWorkloadCount(1);
        var result = ReportValidator.validate(draft);
        assertEquals(true, result.get("ok"));
        assertEquals(false, result.get("missingWorkload"));
        assertEquals(List.of(), result.get("shouldConfirm"));
        assertEquals(new BigDecimal("100"), workload.getQuantity());
    }

    @Test void missingActivityStillBlocksWhenWorkloadIsOptional() {
        ReportDraft draft = draft();draft.getElectricity().clear();
        var result = ReportValidator.validate(draft);
        assertEquals(false, result.get("ok"));
        assertTrue(result.get("mustFix").toString().contains("缺少自动带入的活动数据"));
    }

    @Test void unresolvedSourceIssuesStillBlockWithoutWorkload() {
        for (String code : List.of("UNCONFIRMED_ALLOCATION", "LEGACY_FACTOR_UNIT_CONFLICT", "SOURCE_QUALITY")) {
            ReportDraft draft = draft();
            PrefillResult source = new PrefillResult();
            ReportSourceSnapshot.issue(source, code, 1L, "测试待核对：" + code, true);
            ReportSourceSnapshot.freeze(draft.getTask(), source);
            var result = ReportValidator.validate(draft);
            assertEquals(false, result.get("ok"), code);
            assertTrue(result.get("mustFix").toString().contains(code), result.toString());
        }
    }
}
