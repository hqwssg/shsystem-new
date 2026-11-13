package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Assumptions;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.*;
import com.ruoyi.carbon.report.generation.ReportSnapshotAssembler;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;

class FuelRenderContractTest {
    private static final Map<String,String> VALUES=Map.of("natural_gas","21.621888","gasoline","3.042547","diesel","3.145122");
    @Test void excludesInternalValueWithoutMutatingResolvedPlan() {
        ReportFactorPlan plan=new ReportFactorPlan();plan.setNeeded(new ArrayList<>(VALUES.keySet()));
        for (String fuel:VALUES.keySet()) {
            Map<String,Object> row=new LinkedHashMap<>();BigDecimal value=new BigDecimal(VALUES.get(fuel));
            row.put("value",value);row.put("emission_factor",value);row.put("expected_unit",fuel.equals("natural_gas")?"10k_m3":"t");
            plan.getResolved().put(fuel,row);
        }
        Map<String,Object> snapshot=new ReportFactorResolver(mock(EmissionCalculationMapper.class)).toSnapshot(plan,false);
        JSONObject fuels=JSON.parseObject(JSON.toJSONString(snapshot)).getJSONObject("fuel_factors");
        for (String fuel:VALUES.keySet()) {
            assertFalse(fuels.getJSONObject(fuel).containsKey("value"));
            assertEquals(0,new BigDecimal(VALUES.get(fuel)).compareTo(fuels.getJSONObject(fuel).getBigDecimal("emission_factor")));
            assertTrue(plan.getResolved().get(fuel).containsKey("value"));
        }
    }
    static CalculationNodeDataRow row(long id,String category,String unit,String quantity,String factor) {
        CalculationNodeDataRow r=new CalculationNodeDataRow();r.setId(id);r.setCollectionPointId(id);r.setCollectionPointType(2);
        r.setEnergyAllocation("qa");r.setFacilityName("合成采集点"+id);r.setEmissionSubcategory(category);r.setMeasurementUnit(unit);
        r.setEnergyMeasurementValue(new BigDecimal(quantity));r.setCarbonEmissionFactor(new BigDecimal(factor));
        r.setCarbonEmissionFactorUnit("tCO2/"+unit);r.setCarbonEmissionUnit("tCO2");r.setDataStatus(1);
        r.setCarbonEmission(new BigDecimal(quantity).multiply(new BigDecimal(factor)));return r;
    }
    static String actualJavaSnapshot() {
        ReportTask task=new ReportTask();task.setId(1L);task.setDeptId(3030L);task.setVersion(1);
        CalculationCandidate source=new CalculationCandidate();source.setId(11L);source.setTemplateId(503L);source.setCompanyDeptId(3030L);
        source.setTemplateName("全燃料契约合成测试 非正式");source.setStatus(2);
        source.setCycleStart(java.sql.Date.valueOf("2025-03-01"));source.setCycleEnd(java.sql.Date.valueOf("2025-09-30"));
        CreateReportRequest request=new CreateReportRequest();request.setPeriodMode("CALCULATION");request.setCalculationTemplateId(11L);
        ReportPeriodSnapshot.initialize(task,request,source,"合成测试主体");task.setCalculationTemplateId(11L);
        PrefillResult result=new PrefillAssembler(new ReportUnitConverter()).assemble("qa",List.of(
            row(1,"天然气","wan_m3","1","21.621888"),row(2,"汽油","t","1","3.042547"),
            row(3,"柴油","t","1","3.145122"),row(4,"汽油","t","2","4.5"),
            row(5,"外购电力","MWh","1","0.5306"),row(6,"外购电力","MWh","1","0.61"),
            row(7,"热力数据","GJ","1","0.11")));
        assertTrue(result.getIssues().isEmpty(),result.getIssues().toString());
        result.setCycleStart("2025-03-01");result.setCycleEnd("2025-09-30");
        ReportSourceSnapshot.freeze(task,result);
        ReportDraft draft=new ReportDraft();draft.setTask(task);PrefillCommitter committer=new PrefillCommitter();
        draft.getFuels().addAll(committer.toFuelRows(task,result));draft.getElectricity().addAll(committer.toElectricityRows(task,result));
        draft.getHeat().addAll(committer.toHeatRows(task,result));
        ReportWorkload workload=new ReportWorkload();workload.setName("合成测试工作量 非业务数据");workload.setQuantity(new BigDecimal("1000"));workload.setUnit("测试单位");draft.getWorkload().add(workload);
        JSONObject meta=ReportSourceSnapshot.metadata(task);meta.put("compiler","合成测试编制 非正式");meta.put("compile_date","2026-10-20");task.setMetadataJson(meta.toJSONString());
        ReportDeptProfile profile=new ReportDeptProfile();profile.setEntityCode("jiliang");profile.setLegalName("合成测试主体 非正式");profile.setShortName("合成测试");
        profile.setBusinessDescription("全部数量为合成测试，不代表任何公司实际排放");profile.setCarbonDepartment("测试");
        ReportFactorResolver resolver=new ReportFactorResolver(mock(EmissionCalculationMapper.class));
        return new ReportSnapshotAssembler().assemble(draft,profile,resolver.toSnapshot(resolver.plan(draft),false));
    }
    @Test void actualJavaPayloadPassesPythonAndKeepsDistinctRowFactors() throws Exception {
        String python=System.getProperty("report.contract.python");Assumptions.assumeTrue(python!=null,"Set report.contract.python for Java/Python contract execution");
        String snapshot=actualJavaSnapshot();
        String output=System.getProperty("report.contract.output");
        if(output!=null) {Path target=Path.of(output);Files.createDirectories(target.getParent());Files.writeString(target,snapshot,StandardCharsets.UTF_8);}
        Path root=Path.of(System.getProperty("user.dir")).toAbsolutePath();
        while(root!=null && !Files.exists(root.resolve("carbon_report_agent/models.py")))root=root.getParent();assertNotNull(root);
        String code="import sys;from carbon_report_agent.models import ReportInput;from carbon_report_agent.factors import FactorLibrary;from carbon_report_agent.calculations import calculate_report;r=ReportInput.model_validate_json(sys.stdin.read());c=calculate_report(r,FactorLibrary.from_snapshot(r.factors));assert c.fuel_emissions['gasoline']==12.04;assert c.total_emissions_tco2==38.06;print('JAVA_PYTHON_FUEL_CONTRACT_OK')";
        ProcessBuilder pb=new ProcessBuilder(python,"-c",code);pb.directory(root.toFile());pb.redirectErrorStream(true);pb.environment().put("PYTHONPATH",root.toString());pb.environment().put("PYTHONIOENCODING","utf-8");
        Process process=pb.start();try(var input=process.getOutputStream()){input.write(snapshot.getBytes(StandardCharsets.UTF_8));}
        assertTrue(process.waitFor(45,TimeUnit.SECONDS),"Python contract timeout");String result=new String(process.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
        assertEquals(0,process.exitValue(),result);assertTrue(result.contains("JAVA_PYTHON_FUEL_CONTRACT_OK"),result);
    }
}
