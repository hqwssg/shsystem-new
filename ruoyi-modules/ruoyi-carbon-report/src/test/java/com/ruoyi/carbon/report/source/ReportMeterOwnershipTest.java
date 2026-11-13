package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.*;
import java.math.BigDecimal;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.session.Configuration;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.*;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.common.core.exception.ServiceException;

class ReportMeterOwnershipTest {
    static final Set<String> ALIASES = Set.of("jilong", "机辆分公司");
    static CalculationNodeDataRow row(Long dept, Long company, String legacy) {
        CalculationNodeDataRow r = new CalculationNodeDataRow();
        r.setId(1L); r.setCollectionPointId(90081L);r.setCollectionPointType(2);
        r.setAttributionDeptId(dept);r.setAttributionCompanyDeptId(company);r.setEnergyAllocation(legacy);
        r.setEmissionSubcategory("柴油");r.setFacilityName("柴油采集点");r.setMeasurementUnit("t");
        r.setEnergyMeasurementValue(BigDecimal.TEN);r.setCarbonEmission(new BigDecimal("30"));
        r.setCarbonEmissionFactor(new BigDecimal("3"));r.setCarbonEmissionFactorUnit("tCO2/t");
        r.setCarbonEmissionUnit("tCO2");r.setDataStatus(1);return r;
    }
    static PrefillResult assemble(CalculationNodeDataRow r) {
        return new PrefillAssembler(new ReportUnitConverter()).assembleForCompany(3030L, ALIASES, List.of(r));
    }
    @Test void currentDepartmentAcceptsDieselWithBlankLegacyAndPreservesSource() {
        CalculationNodeDataRow r=row(3030L,3030L,"");
        PrefillResult result=assemble(r);assertEquals(1,result.getLineCount());assertTrue(result.getIssues().isEmpty());
        assertEquals("",r.getEnergyAllocation());assertEquals(new BigDecimal("30"),result.getFuels().get(0).getCarbonEmission());
    }
    @Test void acceptsSubdepartmentResolvedToNearestRegisteredCompany() {
        assertEquals(1,assemble(row(3031L,3030L,null)).getLineCount());
    }
    @Test void legacyCodeAndUniqueChineseNameStillWorkWithoutDepartment() {
        assertEquals(1,assemble(row(null,null,"jilong")).getLineCount());
        assertEquals(1,assemble(row(null,null,"机辆分公司")).getLineCount());
        assertEquals(0,assemble(row(null,null,"")).getLineCount());
    }
    @Test void neverFallsBackFromInvalidDepartmentAndDistinguishesConflict() {
        PrefillResult invalid=assemble(row(99999L,null,"机辆分公司"));
        assertEquals(0,invalid.getLineCount());assertEquals("ALLOCATION_INVALID",invalid.getIssues().get(0).get("code"));
        PrefillResult conflict=assemble(row(3010L,3010L,"机辆分公司"));
        assertEquals(0,conflict.getLineCount());assertEquals("ALLOCATION_CONFLICT",conflict.getIssues().get(0).get("code"));
        assertEquals(0,assemble(row(3030L,3030L,"原平分公司")).getLineCount());
        assertEquals(0,assemble(row(3010L,3010L,"原平分公司")).getLineCount());
    }
    @Test void ownershipChangesInvalidatePreviewButLegacySignaturesKeepSameShape() {
        CalculationNodeDataRow r=row(null,null,"jilong");String old=ReportPeriodSnapshot.sourceSignature(List.of(r));
        String legacyScope=ReportPeriodSnapshot.scopeSignature(List.of(r),ALIASES);
        r.setAttributionDeptId(3030L);r.setAttributionCompanyDeptId(3030L);
        assertNotEquals(old,ReportPeriodSnapshot.sourceSignature(List.of(r)));
        assertEquals(legacyScope,ReportPeriodSnapshot.scopeSignature(List.of(r),3030L,ALIASES));
        r.setAttributionCompanyDeptId(3010L);
        assertNull(ReportPeriodSnapshot.scopeSignature(List.of(r),3030L,ALIASES));
    }
    @Test void mapperProducesOnlyColumnsActuallyPresentForEachMeterType() throws Exception {
        Configuration c=new Configuration();
        try (var in=getClass().getResourceAsStream("/mapper/carbon/report/EmissionCalculationMapper.xml")) {
            new XMLMapperBuilder(in,c,"ownership-mapper",c.getSqlFragments()).parse();
        }
        String name=EmissionCalculationMapper.class.getName()+".selectNodeDataCompatible";
        String old=c.getMappedStatement(name).getBoundSql(Map.of("calculationTemplateId",4178L,"attributionTables",Set.of())).getSql();
        assertFalse(old.contains("fm.energy_attribution_dept_id"));assertFalse(old.contains("em.energy_attribution_dept_id"));
        String mixed=c.getMappedStatement(name).getBoundSql(Map.of("calculationTemplateId",4178L,"attributionTables",Set.of("emission_fossil_fuel_meter_info"))).getSql();
        assertTrue(mixed.contains("fm.energy_attribution_dept_id"));assertFalse(mixed.contains("em.energy_attribution_dept_id"));
        assertFalse(mixed.contains("hm.energy_attribution_dept_id"));
    }
    @Test void refreshedPreviewPreservesOverrideQuantityReasonAndFrozenFactor() {
        PrefillResult initial=assemble(row(null,null,"机辆分公司"));
        ReportTask t=new ReportTask();t.setId(1L);t.setDeptId(3030L);ReportSourceSnapshot.freeze(t,initial);
        PrefillCommitter committer=new PrefillCommitter();List<ReportActivityRow> old=committer.toFuelRows(t,initial);
        committer.overrideNormalized(old.get(0),new BigDecimal("12.5"),"人工核对修正");
        PrefillResult updated=assemble(row(3030L,3030L,""));
        List<ReportActivityRow> kept=committer.protectOverrides(t,old,committer.toFuelRows(t,updated),updated.getFuels());
        assertEquals(new BigDecimal("12.5"),kept.get(0).getNormalizedValue());
        assertEquals("人工核对修正",kept.get(0).getOverrideReason());assertEquals("OVERRIDE",kept.get(0).getDataOrigin());
        assertNotEquals(old.get(0).getSourceHash(),kept.get(0).getSourceHash());
        ReportSourceSnapshot.freeze(t,updated);assertNotNull(ReportSourceSnapshot.line(ReportSourceSnapshot.saved(t),kept.get(0)));
    }
    @Test void reimportRetainsUserEnteredHeatAreaAndCoefficient() {
        CalculationNodeDataRow r=row(null,null,"jilong");r.setEmissionSubcategory("热力数据");r.setMeasurementUnit("GJ");
        r.setCarbonEmissionFactorUnit("tCO2/GJ");PrefillResult initial=assemble(r);ReportTask t=new ReportTask();
        ReportSourceSnapshot.freeze(t,initial);PrefillCommitter c=new PrefillCommitter();List<ReportActivityRow> old=c.toHeatRows(t,initial);
        old.get(0).setHeatingAreaM2(new BigDecimal("1000"));old.get(0).setHeatCoefficient(new BigDecimal("0.8"));
        List<ReportActivityRow> kept=c.protectOverrides(t,old,c.toHeatRows(t,initial),initial.getHeat());
        assertEquals(new BigDecimal("1000"),kept.get(0).getHeatingAreaM2());
        assertEquals(new BigDecimal("0.8"),kept.get(0).getHeatCoefficient());
    }
    @Test void changedFactorOrManualActivityCannotBeOverwritten() {
        PrefillResult initial=assemble(row(null,null,"jilong"));ReportTask t=new ReportTask();
        ReportSourceSnapshot.freeze(t,initial);PrefillCommitter committer=new PrefillCommitter();
        List<ReportActivityRow> old=committer.toFuelRows(t,initial);committer.overrideNormalized(old.get(0),BigDecimal.ONE,"reason");
        CalculationNodeDataRow changed=row(3030L,3030L,"");changed.setCarbonEmissionFactor(BigDecimal.ONE);
        PrefillResult result=assemble(changed);
        assertThrows(ServiceException.class,()->committer.protectOverrides(t,old,committer.toFuelRows(t,result),result.getFuels()));
        old.get(0).setDataOrigin("MANUAL");
        assertThrows(ServiceException.class,()->committer.protectOverrides(t,old,committer.toFuelRows(t,initial),initial.getFuels()));
        assertEquals(BigDecimal.ONE,old.get(0).getNormalizedValue());
    }
}
