package com.ruoyi.carbon.report.source;

import java.math.BigDecimal;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.*;

class ReportSourceSnapshotTest {
    private CalculationNodeDataRow row(String category, String unit, String quantity, String factor, String factorUnit) {
        CalculationNodeDataRow r = new CalculationNodeDataRow(); r.setId(1L); r.setEnergyAllocation("公司甲");
        r.setEmissionSubcategory(category); r.setMeasurementUnit(unit); r.setEnergyMeasurementValue(new BigDecimal(quantity));
        r.setCarbonEmissionFactor(new BigDecimal(factor)); r.setCarbonEmissionFactorUnit(factorUnit); r.setCarbonEmissionUnit("tCO2e");
        r.setDataStatus(1); return r;
    }
    @Test void chineseNaturalGasKeepsTenThousandCubicMetersAndAdjustedPair() {
        var r = row("天然气", "wan_m3", "2", "20", "tCO₂/万Nm³"); r.setCarbonEmission(new BigDecimal("40"));
        r.setAdjustedEnergyValue(new BigDecimal("3")); r.setAdjustedCarbonEmission(new BigDecimal("60"));
        var result = new PrefillAssembler(new ReportUnitConverter()).assemble("公司甲", List.of(r));
        assertEquals(1,result.getLineCount()); assertTrue(result.getGaps().isEmpty());
        var line=result.getFuels().get(0); assertEquals(0,line.getNormalizedValue().compareTo(new BigDecimal("3")));
        assertEquals(0,line.getCarbonEmission().compareTo(new BigDecimal("60"))); assertEquals("ADJUSTED",line.getValueBasis());
    }
    @Test void historicalHeatUnitMixIsBlockedEvenWhenSnapshotArithmeticAgrees() {
        var r = row("热力数据", "GJ", "100", "0.11", "kgCO₂/GJ"); r.setCarbonEmission(new BigDecimal("0.011"));
        r.setTemplateFactor(new BigDecimal("0.11")); r.setTemplateFactorUnit("tCO₂/GJ");
        var result = new PrefillAssembler(new ReportUnitConverter()).assemble("公司甲",List.of(r));
        assertEquals(1,result.getLineCount());
        assertTrue(result.getIssues().stream().anyMatch(i -> "LEGACY_FACTOR_UNIT_CONFLICT".equals(i.get("code"))));
    }
    @Test void missingAllocationAndNoDataNeverBecomeZeroActivity() {
        var r=row("柴油","t","0","3","tCO2/t");r.setDataStatus(2); r.setCarbonEmission(BigDecimal.ZERO);
        var assembler = new PrefillAssembler(new ReportUnitConverter());
        assertEquals(0,assembler.assemble("公司甲",List.of(r)).getLineCount());
        r.setEnergyAllocation(null); var result=assembler.assemble("公司甲",List.of(r));
        assertTrue(result.getIssues().stream().anyMatch(i -> "ALLOCATION_MISSING".equals(i.get("code"))));
    }
    @Test void unsupportedFactorUnitFailsClosedAndElectricityUnitsAreEquivalent() {
        assertNull(ReportSourceSnapshot.factor("PH_HD",BigDecimal.ONE,"mystery/GJ"));
        assertNull(ReportSourceSnapshot.factor("PH_HA",BigDecimal.ONE,"tCO2/m2"));
        assertEquals(0,ReportSourceSnapshot.factor("PE",new BigDecimal("0.5"),"kgCO₂/kWh").compareTo(new BigDecimal("0.5")));
    }
    @Test void duplicateAllocationCodeDoesNotAuthorizeEitherCompanyName() {
        ReportSubjectOption a = new ReportSubjectOption();a.setDeptId(1L);a.setDeptName("公司甲");a.setEnergyAllocation("shared");
        ReportSubjectOption b = new ReportSubjectOption();b.setDeptId(2L);b.setDeptName("公司乙");b.setEnergyAllocation("shared");
        assertTrue(ReportAllocationScope.accepted(1L,a,a,List.of(a,b)).isEmpty());
        b.setEnergyAllocation("other"); assertEquals(Set.of("shared","公司甲"),ReportAllocationScope.accepted(1L,a,a,List.of(a,b)));
    }
    @Test void frozenIssuesSurviveSerializationAndCannotBeReplacedByBasicForm() {
        ReportTask task=new ReportTask();task.setCalculationTemplateId(9L);
        PrefillResult result=new PrefillResult();ReportSourceSnapshot.issue(result,"ALLOCATION_MISSING",1L,"归属待确认",true);
        ReportSourceSnapshot.freeze(task,result);
        task.setMetadataJson(ReportSubjectSnapshot.preserveOnBasicSave(task.getMetadataJson(),"{\"_source_snapshot\":{},\"compiler\":\"甲\"}"));
        ReportDraft draft=new ReportDraft();draft.setTask(task);
        assertTrue(ReportSourceSnapshot.problems(draft).contains("归属待确认"));
        assertEquals("甲",JSON.parseObject(task.getMetadataJson()).getString("compiler"));
        assertEquals(1,ReportSourceSnapshot.saved(task).toJavaObject(PrefillResult.class).getIssues().size());
    }
}
