package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.MonthlyAnalysisRequest;
import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.security.*;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.*;
import org.springframework.web.server.ResponseStatusException;
import java.math.BigDecimal;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class MonthlyAnalysisDataServiceTest {
    final JdbcTemplate jdbc=mock(JdbcTemplate.class);
    final TemplateRepository templates=mock(TemplateRepository.class);
    final EmissionNodeRepository nodes=mock(EmissionNodeRepository.class);
    final EmissionNodeConfigRepository configs=mock(EmissionNodeConfigRepository.class);
    final CompanyOwnershipService companies=mock(CompanyOwnershipService.class);
    final CarbonDataScopeService scopes=mock(CarbonDataScopeService.class);
    final CollectionScopeService points=mock(CollectionScopeService.class);
    final NodeInclusionResolver inclusion=mock(NodeInclusionResolver.class);
    final MonthlyAnalysisDataService service=new MonthlyAnalysisDataService(jdbc,templates,nodes,configs,companies,
            mock(StatisticsBaselineTemplateService.class),scopes,points,inclusion);
    Template template; MonthlyAnalysisRequest request;

    @BeforeEach @SuppressWarnings("unchecked") void setup() {
        bind(Set.of("carbon:analysis:view"),List.of());
        template=new Template();template.setId(7L);template.setDeptId(3030L);template.setTemplateType(2);template.setName("统计模板");
        when(companies.accessibleOptions()).thenReturn(List.of(new CompanyOwnershipService.Company(3030L,"机辆")));
        when(templates.findById(7L)).thenReturn(Optional.of(template));when(scopes.canReadSafely(template)).thenReturn(true);
        EmissionNode node=new EmissionNode();node.setId(11L);node.setTemplateId(7L);node.setTypeId(3);node.setName("点");
        when(nodes.findByTemplateId(7L)).thenReturn(List.of(node));
        when(inclusion.resolve(anyList())).thenReturn(Map.of(11L,new NodeInclusionResolver.InclusionDecision(true,null)));
        EmissionNodeConfig config=new EmissionNodeConfig();config.setNodeId(11L);config.setCollectionPointType(1);config.setCollectionPointId(90000L);
        when(configs.findCollectionPointConfigsByTemplateId(7L)).thenReturn(List.of(config,config));
        when(points.canView("electricity","meter",90000L)).thenReturn(true);
        when(jdbc.queryForList(contains("from emission_meter_info"),eq(90000L)))
                .thenAnswer(i -> List.of(new HashMap<>(Map.of("name","演示电表","emission_subcategory","电力","measurement_unit","MWh"))));
        when(jdbc.query(anyString(),any(RowMapper.class),any(Object[].class))).thenReturn(List.of());
        request=new MonthlyAnalysisRequest();request.setStartMonth("2025-01");request.setEndMonth("2025-03");
        var selection=new MonthlyAnalysisRequest.Selection();selection.setCompanyId(3030L);selection.setTemplateId(7L);request.setSelections(List.of(selection));
    }
    @AfterEach void reset() { RequestContextHolder.resetRequestAttributes(); }

    @Test void analysisOnlyPermissionCanReadCrossYearPointRangeWithoutDuplicateRows() {
        request.setStartMonth("2024-12");request.setEndMonth("2025-02");
        var result=service.load(request);
        assertThat(result).hasSize(3);assertThat(result.get(0).month()).isEqualTo("2024-12");
        assertThat(result).allSatisfy(d -> { assertThat(d.data().getId()).isNull();assertThat(d.data().getDataMissingDescription()).isEqualTo("未生成月度结果"); });
        verify(points).canView("electricity","meter",90000L);
    }
    @Test void unauthorizedCompanyTemplateAndNodeNeverReturnRows() {
        request.getSelections().get(0).setCompanyId(3020L);
        assertThatThrownBy(() -> service.load(request)).isInstanceOf(ResponseStatusException.class).hasMessageContaining("公司");
        request.getSelections().get(0).setCompanyId(3030L);request.getSelections().get(0).setNodeId(999L);
        assertThatThrownBy(() -> service.load(request)).hasMessageContaining("核算点");
        request.getSelections().get(0).setNodeId(null);template.setDeptId(3020L);
        assertThatThrownBy(() -> service.load(request)).hasMessageContaining("模板");
    }
    @Test void physicalScopeAndInheritedExclusionAreRespected() {
        when(points.canView(anyString(),anyString(),anyLong())).thenReturn(false);
        assertThat(service.load(request)).isEmpty();
        when(inclusion.resolve(anyList())).thenReturn(Map.of(11L,new NodeInclusionResolver.InclusionDecision(false,11L)));
        assertThat(service.load(request)).isEmpty();
    }
    @Test void assignedAccountingNodesAreIntersectedWithTheTemplate() {
        bind(Set.of("carbon:analysis:view"),List.of(99L));
        assertThat(service.load(request)).isEmpty();
    }
    @Test @SuppressWarnings("unchecked") void duplicatePointReferencesKeepBothAuthorizedNodeChoicesVisible() {
        var alias=new EmissionNode();alias.setId(12L);alias.setTemplateId(7L);alias.setTypeId(3);alias.setName("同表另一引用");
        var first=nodes.findByTemplateId(7L).get(0);when(nodes.findByTemplateId(7L)).thenReturn(List.of(first,alias));
        var c1=configs.findCollectionPointConfigsByTemplateId(7L).get(0);
        var c2=new EmissionNodeConfig();c2.setNodeId(12L);c2.setCollectionPointType(1);c2.setCollectionPointId(90000L);
        when(configs.findCollectionPointConfigsByTemplateId(7L)).thenReturn(List.of(c1,c2));
        when(inclusion.resolve(anyList())).thenReturn(Map.of(11L,new NodeInclusionResolver.InclusionDecision(true,null),12L,new NodeInclusionResolver.InclusionDecision(true,null)));
        when(templates.findAllByOrderByCreatedAtDesc()).thenReturn(List.of(template));
        var options=service.options();var company=((List<Map<String,Object>>)options.get("companies")).get(0);
        var choice=((List<Map<String,Object>>)company.get("templates")).get(0);
        assertThat((List<Map<String,Object>>)choice.get("nodes")).extracting(n -> n.get("id")).containsExactly(11L,12L);
        assertThat(service.load(request)).hasSize(3);
    }
    @Test @SuppressWarnings("unchecked") void missingMonthlyTableHasExplicitDeploymentError() {
        when(jdbc.query(anyString(),any(RowMapper.class),any(Object[].class)))
                .thenThrow(new BadSqlGrammarException("read","monthly",new java.sql.SQLException("missing table")));
        assertThatThrownBy(() -> service.load(request)).hasMessageContaining("月度表迁移");
    }
    @Test void validatesEmptyNullAndNonCalendarQuarterFilters() {
        request.setValueMode(null);assertThatThrownBy(() -> service.load(request)).isInstanceOf(ResponseStatusException.class);
        request.setValueMode("RAW");request.setGrain("QUARTER");request.setStartMonth("2025-02");
        assertThatThrownBy(() -> service.load(request)).hasMessageContaining("自然季度");
        request.setGrain("YEAR");assertThatThrownBy(() -> service.load(request)).hasMessageContaining("自然年");
        bind(Set.of(),List.of());assertThatThrownBy(() -> service.load(request)).hasMessageContaining("权限");
    }
    @Test void rawAdjustedAndAdoptedKeepZeroMissingAndMatchedPairs() {
        var row=new MonthlyCollectionNodeData();row.setDataStatus(3);row.setEnergyMeasurementValue(BigDecimal.ZERO);row.setCarbonEmission(BigDecimal.ZERO);
        row.setAdjustedEnergyValue(new BigDecimal("10"));row.setAdjustedCarbonEmission(new BigDecimal("5"));
        assertThat(MonthlyAnalysisValues.select(row,"RAW").energy()).isEqualByComparingTo("0");
        assertThat(MonthlyAnalysisValues.select(row,"ADOPTED").carbon()).isEqualByComparingTo("5");
        row.setTotalEmissionCalcMethod(2);assertThat(MonthlyAnalysisValues.select(row,"ADOPTED").carbon()).isEqualByComparingTo("0");
        row.setAdjustedEnergyValue(null);assertThat(MonthlyAnalysisValues.select(row,"ADJUSTED").energy()).isNull();
        row.setDataStatus(2);assertThat(MonthlyAnalysisValues.select(row,"RAW").energy()).isNull();
        assertThat(MonthlyAnalysisValues.difference(null,BigDecimal.ZERO)).isNull();
    }
    @Test void postAnalysisEndpointsUseViewPermission() {
        for(String path:List.of("options","query","compare","details","export"))
            assertThat(CarbonPermissionResolver.requiredPermissions("POST","/api/monthly-analysis/"+path)).containsExactly("carbon:analysis:view");
    }
    private void bind(Set<String> permissions,List<Long> nodeIds) {
        var http=new MockHttpServletRequest();http.setAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE,new CarbonSecurityContext(1L,"test","test",3030L,"company",Set.of(),permissions,false,false,List.of(3030L),nodeIds));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(http));
    }
}
