package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.*;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.*;
import com.ruoyi.carbon.report.generation.ReportSnapshotAssembler;
import com.ruoyi.carbon.report.mapper.*;
import com.ruoyi.common.core.exception.ServiceException;
import org.junit.jupiter.api.Test;

class ReportPeriodContractTest {
    static java.sql.Date date(String text) { return java.sql.Date.valueOf(text); }
    static CalculationCandidate candidate(long id, String start, String end) {
        CalculationCandidate c=new CalculationCandidate();c.setId(id);c.setTemplateId(503L);
        c.setCompanyDeptId(3030L);c.setStatus(2);c.setTemplateName("测试模板");
        c.setCycleStart(date(start));c.setCycleEnd(date(end));return c;
    }
    static ReportTask task(String start, String end) {
        ReportTask t=new ReportTask();t.setDeptId(3030L);
        CreateReportRequest r=new CreateReportRequest();r.setPeriodMode("CALCULATION");r.setCalculationTemplateId(4178L);
        CalculationCandidate c=candidate(4178,start,end);
        ReportPeriodSnapshot.initialize(t,r,c,"机辆分公司");t.setCalculationTemplateId(c.getId());
        return t;
    }
    static CalculationNodeDataRow row(long meter) {
        CalculationNodeDataRow row=new CalculationNodeDataRow();row.setId(11L);row.setCollectionPointType(1);
        row.setCollectionPointId(meter);row.setEnergyAllocation("jilong");row.setEmissionSubcategory("外购电力");
        row.setMeasurementUnit("MWh");row.setDataStatus(1);row.setEnergyMeasurementValue(new BigDecimal("10"));
        row.setCarbonEmission(new BigDecimal("5"));row.setCarbonEmissionUnit("tCO2");
        row.setCarbonEmissionFactor(new BigDecimal("0.5"));row.setCarbonEmissionFactorUnit("tCO2/MWh");
        return row;
    }
    @Test void classifiesInclusiveNaturalPeriodsAndRanges() {
        for (String[] c:new String[][]{{"2025-01-01","2025-12-31","YEAR"},{"2024-02-01","2024-02-29","MONTH"},
            {"2025-03-01","2025-05-31","RANGE"},{"2024-01-01","2025-05-31","RANGE"},
            {"2022-01-01","2025-12-31","RANGE"},{"2025-03-05","2025-05-17","RANGE"},{"2024-06-01","2025-05-31","RANGE"}}) {
            ReportTask t=task(c[0],c[1]);assertEquals(c[2],t.getPeriodType());
            assertTrue(t.getTitle().contains(c[0]+"至"+c[1]));assertEquals(Integer.valueOf(c[1].substring(0,4)),t.getReportYear());
        }
        assertThrows(ServiceException.class,()->ReportPeriodSnapshot.classify(LocalDate.of(2025,2,1),LocalDate.of(2025,1,1)));
    }
    @Test void freezesSourceAndRejectsDifferentTaskOrDates() {
        ReportTask t=task("2025-03-01","2025-05-31");
        ReportPeriodSnapshot.requireSelection(t,4178L,candidate(4178,"2025-03-01","2025-05-31"));
        assertThrows(ServiceException.class,()->ReportPeriodSnapshot.requireSelection(t,4172L,candidate(4172,"2025-01-01","2025-12-31")));
        assertThrows(ServiceException.class,()->ReportPeriodSnapshot.requireSelection(t,4178L,candidate(4178,"2025-03-01","2025-06-30")));
        assertFalse(ReportPeriodSnapshot.enabled(new ReportTask()));
        String original=t.getMetadataJson();
        t.setMetadataJson(ReportSubjectSnapshot.preserveOnBasicSave(original,"{\"compiler\":\"新编制单位\",\"_report_period\":{\"version\":0}}"));
        assertEquals(ReportPeriodSnapshot.saved(JSONTask(original)),ReportPeriodSnapshot.saved(t));
    }
    static ReportTask JSONTask(String json) { ReportTask t=new ReportTask();t.setMetadataJson(json);return t; }
    @Test void rejectsClientPeriodOverrideAndSupportsBlankManualReport() {
        CreateReportRequest r=new CreateReportRequest();r.setPeriodMode("CALCULATION");r.setPeriodStart("2025-01-01");
        assertThrows(ServiceException.class,()->ReportPeriodSnapshot.initialize(new ReportTask(),r,candidate(1,"2025-03-01","2025-05-31"),"公司"));
        r.setPeriodMode("MANUAL");r.setPeriodStart("2025-03-05");r.setPeriodEnd("2025-05-17");
        ReportTask t=new ReportTask();ReportPeriodSnapshot.initialize(t,r,null,"公司");
        assertEquals("公司（2025-03-05至2025-05-17）碳排放报告",t.getTitle());assertEquals("RANGE",t.getPeriodType());
    }
    @Test void sourceHashTracksPersistedEvidenceButIgnoresDecimalScale() {
        CalculationNodeDataRow a=row(90148);String hash=ReportPeriodSnapshot.sourceSignature(List.of(a));
        a.setEnergyMeasurementValue(new BigDecimal("10.000000"));assertEquals(hash,ReportPeriodSnapshot.sourceSignature(List.of(a)));
        a.setTemplateFactor(new BigDecimal("0.9"));a.setTemplateFactorUnit("tCO2/MWh");
        assertEquals(hash,ReportPeriodSnapshot.sourceSignature(List.of(a))); // Live template edits do not rewrite persisted factors.
        a.setCarbonEmissionFactor(new BigDecimal("0.7"));assertNotEquals(hash,ReportPeriodSnapshot.sourceSignature(List.of(a)));
    }
    @Test void rendererGetsDistinctCompanyTitleDatesAndNoInternalMetadata() {
        ReportTask t=task("2024-01-01","2025-05-31");ReportDraft d=new ReportDraft();d.setTask(t);
        JSONObject snapshot=JSON.parseObject(new ReportSnapshotAssembler().assemble(d,null));
        assertEquals("range",snapshot.getString("period_grain"));assertEquals(1,snapshot.getIntValue("period_contract_version"));
        JSONObject meta=snapshot.getJSONObject("metadata");assertEquals("机辆分公司",meta.getString("entity_name"));
        assertEquals(t.getTitle(),meta.getString("report_title"));assertEquals("测试模板",meta.getString("template_name"));
        assertFalse(meta.keySet().stream().anyMatch(k->k.startsWith("_")));
        assertEquals("A_B_C.pdf",ReportPeriodSnapshot.fileName("A/B:C","pdf"));
    }
    @Test void comparisonsRequireExactPeriodSameMeterScopeAndHealthyDataAndFreezeAdoption() {
        ReportTask t=task("2024-02-01","2024-02-29");
        JSONObject p=ReportPeriodSnapshot.saved(t);p.put("scopeSignature",ReportPeriodSnapshot.scopeSignature(List.of(row(90148)),Set.of("jilong")));
        JSONObject meta=JSON.parseObject(t.getMetadataJson());meta.put(ReportPeriodSnapshot.KEY,p);t.setMetadataJson(meta.toJSONString());
        EmissionCalculationMapper cm=mock(EmissionCalculationMapper.class);ReportDeptSubjectMapper sm=mock(ReportDeptSubjectMapper.class);
        ReportDeptSubject subject=new ReportDeptSubject();subject.setDeptId(3030L);subject.setSubjectNodeId(1001L);subject.setEnergyAllocation("jilong");
        when(sm.selectByDeptId(3030L)).thenReturn(subject);when(sm.selectCompanies(any())).thenReturn(List.of());
        CalculationCandidate one=candidate(1,"2023-02-01","2023-02-28"),two=candidate(2,"2023-02-01","2023-02-28");
        CalculationCandidate overlap=candidate(3,"2023-01-01","2023-12-31"),other=candidate(4,"2023-02-01","2023-02-28");other.setCompanyDeptId(3010L);
        when(cm.selectCompanyCandidates(eq(3030L),any(),any())).thenAnswer(invocation ->
            date("2023-02-01").equals(invocation.getArgument(1)) ? List.of(one,two,overlap,other) : List.of());
        when(cm.selectNodeData(1L)).thenReturn(List.of(row(90148)));when(cm.selectNodeData(2L)).thenReturn(List.of(row(90148)));
        ReportComparisonService service=new ReportComparisonService(cm,sm);
        JSONObject slots=service.candidates(t);assertEquals(2,slots.getJSONObject("yoy").getJSONArray("candidates").size());
        assertEquals(0,slots.getJSONObject("mom").getJSONArray("candidates").size());
        assertEquals("2023-02-28",slots.getJSONObject("yoy").getString("end"));
        JSONObject option=slots.getJSONObject("yoy").getJSONArray("candidates").getJSONObject(0);
        JSONObject pick=new JSONObject();pick.put("mode","TASK");pick.put("taskId",1);pick.put("selectionHash",option.getString("selectionHash"));
        JSONObject input=new JSONObject();input.put("yoy",pick);String adopted=service.save(t,input.toJSONString());t.setPriorYearJson(adopted);
        when(cm.selectNodeData(1L)).thenReturn(List.of(row(99999))); // Source changed after adoption: KEEP remains frozen.
        assertEquals(adopted,service.save(t,"{\"yoy\":{\"mode\":\"KEEP\"}}"));
        assertThrows(ServiceException.class,()->service.save(t,input.toJSONString()));
        t.setOrganizationBoundaryJson("{\"boundary_description\":\"changed\"}");
        assertFalse(ReportComparisonService.problems(t).isEmpty());
        assertThrows(ServiceException.class,()->service.save(t,"{\"yoy\":{\"mode\":\"KEEP\"}}"));
    }
}
