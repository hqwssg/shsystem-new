package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.MonthlyAnalysisRequest;
import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.*;
import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.util.*;
import static com.example.carbon.emission.model.service.impl.MonthlyAnalysisDataService.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class MonthlyAnalysisServiceTest {
    MonthlyAnalysisRequest request;
    @BeforeEach void setup() {
        request=new MonthlyAnalysisRequest();request.setStartMonth("2025-01");request.setEndMonth("2025-12");request.setCompareType("NONE");
        var selection=new MonthlyAnalysisRequest.Selection();selection.setCompanyId(3010L);selection.setTemplateId(1L);request.setSelections(List.of(selection));
        var http=new MockHttpServletRequest();http.setAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE,new CarbonSecurityContext(1L,"test","test",3010L,"company",Set.of(),Set.of("carbon:analysis:view"),true,false,List.of(),List.of()));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(http));
    }
    @AfterEach void reset() {RequestContextHolder.resetRequestAttributes();}
    @SuppressWarnings("unchecked") List<Map<String,Object>> rows(Map<String,Object> result) {return (List<Map<String,Object>>)result.get("rows");}
    @SuppressWarnings("unchecked") Map<String,Object> summary(Map<String,Object> result) {return (Map<String,Object>)result.get("summary");}
    Detail record(int month,String raw,String adjusted,int method) {
        var data=new MonthlyCollectionNodeData();data.setId((long)month);data.setYear(2025);data.setMonth(month);data.setEmissionSubcategory("diesel");data.setMeasurementUnit("t");data.setCarbonEmissionUnit("tCO2e");data.setEnergyCategoryL1("PROD");data.setEnergyCategoryL2("TRACTION");data.setDataStatus(1);data.setTotalEmissionCalcMethod(method);
        data.setEnergyMeasurementValue(raw==null?null:new BigDecimal(raw));data.setCarbonEmission(raw==null?null:new BigDecimal(raw).multiply(new BigDecimal("3")));
        data.setAdjustedEnergyValue(adjusted==null?null:new BigDecimal(adjusted));data.setAdjustedCarbonEmission(adjusted==null?null:new BigDecimal(adjusted).multiply(new BigDecimal("3")));
        return new Detail(3010L,"肃宁（合成测试）",1L,"合成测试模板",new Point(2,900L),"合成测试-柴油",String.format("2025-%02d",month),data);
    }
    Map<String,Object> aggregate(List<Detail> details) {return MonthlyAnalysisService.aggregate(details,request,Map.of("SCENE:PROD","生产","SCENE:TRACTION","牵引"));}
    @Test void monthQuarterYearUseSameMonthlySumAndChooseBasisPerRecord() {
        var data=List.of(record(1,"10","12",1),record(2,"20","25",2),record(3,"30","33",1));
        for(String grain:List.of("MONTH","QUARTER","YEAR")) {
            request.setGrain(grain);var result=aggregate(data);
            assertThat((BigDecimal)summary(result).get("selectedCarbon")).isEqualByComparingTo("195");
            assertThat((BigDecimal)summary(result).get("rawCarbon")).isEqualByComparingTo("180");
            assertThat((BigDecimal)summary(result).get("adjustedCarbon")).isEqualByComparingTo("210");
            assertThat(rows(result)).hasSize(grain.equals("MONTH")?3:1);
        }
    }
    @Test void zeroMissingAndNullNeverFallBackToAnotherBasis() {
        var zero=record(1,"0","0",2);var missing=record(2,"99","100",1);missing.data().setDataStatus(2);
        var nullAdjusted=record(3,"50",null,1);var result=aggregate(List.of(zero,missing,nullAdjusted));
        assertThat((BigDecimal)summary(result).get("selectedCarbon")).isEqualByComparingTo("0");
        assertThat(summary(result)).containsEntry("missingCount",2).containsEntry("incomplete",true);
        assertThat(rows(result).get(1).get("selectedEnergy")).isNull();
        request.setValueMode("RAW");assertThat((BigDecimal)summary(aggregate(List.of(zero,missing,nullAdjusted))).get("selectedCarbon")).isEqualByComparingTo("150");
    }
    @Test void deduplicatesPhysicalKeysAndKeepsDifferentUnitsSeparate() {
        var a=record(1,"10","12",1);var b=record(1,"4","5",2);b.data().setMeasurementUnit("L");
        b=new Detail(3010L,"肃宁",1L,"模板",new Point(1,900L),"另一表",b.month(),b.data());
        var result=aggregate(List.of(a,a,b));
        assertThat(rows(result)).hasSize(2);assertThat((BigDecimal)summary(result).get("selectedCarbon")).isEqualByComparingTo("48");
        assertThat(summary(result)).containsEntry("expectedCount",2);
        assertThat((List<?>)summary(result).get("energies")).hasSize(2);
    }
    @Test void sceneLevelsAndUnknownAttributionUseMonthlySnapshot() {
        var d=record(1,"10","12",1);request.setDimension("SCENE");
        assertThat(rows(aggregate(List.of(d))).get(0)).containsEntry("groupName","生产");request.setCategoryLevel(2);
        assertThat(rows(aggregate(List.of(d))).get(0)).containsEntry("groupName","牵引");request.setDimension("DEPARTMENT");
        assertThat(rows(aggregate(List.of(d))).get(0)).containsEntry("groupName","未明确归属");
    }
    @Test void comparisonsShiftEachPeriodAndKeepZeroBaselineRateNull() {
        request.setStartMonth("2025-03");request.setEndMonth("2025-09");request.setCompareType("MOM");
        assertThat(MonthlyAnalysisService.previousRequest(request).getStartMonth()).isEqualTo("2025-02");
        assertThat(MonthlyAnalysisService.previousRequest(request).getEndMonth()).isEqualTo("2025-08");
        request.setCompareType("YOY");request.setStartMonth("2024-02");request.setEndMonth("2024-02");
        assertThat(MonthlyAnalysisService.previousRequest(request).getStartMonth()).isEqualTo("2023-02");
        request.setGrain("QUARTER");request.setCompareType("MOM");request.setStartMonth("2025-01");request.setEndMonth("2025-03");
        assertThat(MonthlyAnalysisService.previousRequest(request).getStartMonth()).isEqualTo("2024-10");
        request.setGrain("MONTH");var now=aggregate(List.of(record(2,"10","12",1)));var then=aggregate(List.of(record(1,"0","0",1)));
        var result=MonthlyAnalysisService.pair(now,then,request);
        assertThat(rows(result).get(0)).containsEntry("previousPeriod","2025-01").containsEntry("rateCarbon",null);
        assertThat((BigDecimal)rows(result).get(0).get("deltaCarbon")).isEqualByComparingTo("36");
        request.setGrain("YEAR");assertThat(MonthlyAnalysisService.shift(request)).isEqualTo(12);
    }
    @Test void nodeRollupSumsOnlyRootsAndKeepsIncompleteVisible() {
        var source=mock(MonthlyAnalysisDataService.class);
        var stored=new java.util.concurrent.atomic.AtomicReference<List<Map<String,Object>>>(List.of(
                nodeRow(null, 10, 30, 1), nodeRow(5L, 4, 12, 2)));
        var jdbc=mock(JdbcTemplate.class, invocation -> "queryForList".equals(invocation.getMethod().getName())
                ? String.valueOf((Object) invocation.getArgument(0)).contains("emission_calc_node_summary_month") ? stored.get() : List.of()
                : org.mockito.Mockito.RETURNS_DEFAULTS.answer(invocation));
        Map<String,Object> selection=new LinkedHashMap<>();
        selection.put("companyId",3010L);selection.put("companyName","肃宁");selection.put("templateId",1L);selection.put("nodeId",null);
        when(source.authorizedSelections(any())).thenReturn(List.of(selection));
        request.setRollup("CALC_NODE");request.setDimension("ENERGY");
        var result=new MonthlyAnalysisService(source,jdbc).query(request);
        assertThat(rows(result)).hasSize(1);
        assertThat((BigDecimal)rows(result).get(0).get("selectedCarbon")).isEqualByComparingTo("30");
        assertThat((BigDecimal)rows(result).get(0).get("directCarbon")).isEqualByComparingTo("10");
        assertThat(rows(result).get(0)).containsEntry("incomplete",false);
        stored.set(List.of(nodeRow(null, 10, 30, 2)));
        var incomplete=new MonthlyAnalysisService(source,jdbc).query(request);
        assertThat(rows(incomplete).get(0)).containsEntry("incomplete",true);
        assertThat((List<String>)incomplete.get("notices")).anyMatch(note -> note.contains("不能视为完整真实值"));
    }
    @Test void collectionQueryKeepsSceneAndDepartmentOnCollectionRows() {
        var source=mock(MonthlyAnalysisDataService.class);
        when(source.load(any())).thenReturn(List.of(record(1,"10","12",1)));
        var jdbc=mock(JdbcTemplate.class, invocation -> "queryForList".equals(invocation.getMethod().getName())
                ? String.valueOf((Object) invocation.getArgument(0)).contains("emission_calc_node_summary_month")
                    ? List.of(nodeRow(null, 99, 99, 1))
                    : List.of(Map.of("code","PROD","name","生产"), Map.of("code","TRACTION","name","牵引"), Map.of("code","diesel","name","柴油"))
                : org.mockito.Mockito.RETURNS_DEFAULTS.answer(invocation));
        request.setDimension("SCENE");request.setCategoryLevel(1);
        var scene=new MonthlyAnalysisService(source,jdbc).query(request);
        assertThat(rows(scene).get(0)).containsEntry("groupName","生产");
        assertThat((BigDecimal)rows(scene).get(0).get("selectedCarbon")).isEqualByComparingTo("36");
        request.setDimension("DEPARTMENT");
        var department=new MonthlyAnalysisService(source,jdbc).query(request);
        assertThat(rows(department).get(0)).containsEntry("groupName","未明确归属");
        assertThat((BigDecimal)rows(department).get(0).get("selectedCarbon")).isEqualByComparingTo("36");
        verify(source, times(2)).load(any());
    }
    private static Map<String,Object> nodeRow(Long parent, int direct, int subtotal, int status) {
        Map<String,Object> row=new LinkedHashMap<>();
        row.put("source_node_id", 8L);row.put("parent_source_node_id", parent);row.put("year", 2025);row.put("month", 1);
        row.put("emission_subcategory","diesel");row.put("direct_energy_value",new BigDecimal(direct));
        row.put("direct_carbon_emission",new BigDecimal(direct));row.put("subtotal_energy_value",new BigDecimal(subtotal));
        row.put("subtotal_carbon_emission",new BigDecimal(subtotal));row.put("calculation_unit_code","t");
        row.put("result_status", status);row.put("missing_collection_point_ids", status==2 ? "15" : null);
        return row;
    }
    @Test void exportReadsTheSameMonthlyRowsAndPreservesBlankCells() throws Exception {
        var source=mock(MonthlyAnalysisDataService.class);var jdbc=mock(JdbcTemplate.class);
        when(source.load(any())).thenReturn(List.of(record(1,"10","12",1),record(2,"20",null,1)));
        when(source.namedOptions(anySet(),anyBoolean())).thenReturn(List.of());
        var service=new MonthlyAnalysisService(source,jdbc);
        String sampleDir=System.getProperty("monthly.analysis.sampleDir");
        for(String mode:List.of("RAW","ADJUSTED","ADOPTED")) {
            request.setValueMode(mode);byte[] bytes=service.export(request);
            try(var sample=new XSSFWorkbook(new ByteArrayInputStream(bytes))) {
                assertThat(sample.getSheet("期间合计").getRow(2).getCell(3).getNumericCellValue()).isEqualTo(mode.equals("RAW")?90:36);
            }
            if(sampleDir!=null) {
                var directory=java.nio.file.Path.of(sampleDir);java.nio.file.Files.createDirectories(directory);
                java.nio.file.Files.write(directory.resolve("synthetic-export-"+mode+".xlsx"),bytes);
            }
        }
        request.setValueMode("ADOPTED");
        try(var book=new XSSFWorkbook(new ByteArrayInputStream(service.export(request)))) {
            assertThat(book.getNumberOfSheets()).isEqualTo(4);
            assertThat(book.getSheet("统计汇总").getRow(1).getCell(5).getNumericCellValue()).isEqualTo(12);
            assertThat(book.getSheet("本期修正明细").getRow(2).getCell(11)).isNull();
            assertThat(book.getSheet("期间合计").getRow(2).getCell(3).getNumericCellValue()).isEqualTo(36);
        }
    }
}
