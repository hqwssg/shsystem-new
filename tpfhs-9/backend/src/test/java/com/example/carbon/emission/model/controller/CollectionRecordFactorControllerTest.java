package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import com.example.carbon.emission.model.service.impl.EffectiveFactorResolver;
import com.example.carbon.emission.model.service.impl.FactorDimensionService;
import com.example.carbon.emission.model.security.CollectionScopeService;
import com.example.carbon.emission.model.service.EmissionDataFreshnessService;
import com.example.carbon.emission.model.service.SystemConfigService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CollectionRecordFactorControllerTest {

    @Test
    void resolvesFactorForTheExactTemplateNodeAndReturnsSourceSnapshot() {
        Fixture fixture = fixture();
        when(fixture.nodeRepository.findById(31L)).thenReturn(Optional.of(node(31L, 9L)));
        when(fixture.configRepository.findByNodeId(31L)).thenReturn(Optional.of(config(31L, 3, 88L)));
        Template template = new Template();
        template.setId(9L);
        template.setFactorTemplateId(77L);
        when(fixture.templateRepository.findById(9L)).thenReturn(Optional.of(template));
        when(fixture.jdbc.queryForMap(org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.eq(88L)))
                .thenReturn(Map.of("id", 88L, "emission_subcategory", "PH_HD",
                        "measurement_unit", "GJ", "meter_reading_method", 0,
                        "is_cumulative", 0, "status", 1, "name", "热力采集点"));
        when(fixture.resolver.resolve(org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.eq(77L), org.mockito.ArgumentMatchers.eq("PH_HD")))
                .thenReturn(new EffectiveFactorResolver.FactorSnapshot(
                        new BigDecimal("0.11"), "tCO₂/GJ", "热力因子",
                        EffectiveFactorResolver.SOURCE_TEMPLATE_DEFAULT));
        when(fixture.dimension.calculate("PH_HD", BigDecimal.ONE, "GJ",
                new BigDecimal("0.11"), "tCO₂/GJ"))
                .thenReturn(new FactorDimensionService.CarbonResult(
                        BigDecimal.ONE, new BigDecimal("0.11"), "tCO₂/GJ", "GJ"));

        Map<String, Object> result = fixture.controller.factor(31L, 3, 88L).getBody();

        assertThat(result).containsEntry("carbonEmissionFactor", new BigDecimal("0.11"))
                .containsEntry("carbonEmissionFactorUnit", "tCO₂/GJ")
                .containsEntry("factorSource", EffectiveFactorResolver.SOURCE_TEMPLATE_DEFAULT)
                .containsEntry("emissionPerActivityUnitTco2e", new BigDecimal("0.11"));
        verify(fixture.scopes).requireCollectionPoint(3, 88L, false);
    }

    @Test
    void rejectsWhenNodeDoesNotReferenceRequestedCollectionPoint() {
        Fixture fixture = fixture();
        when(fixture.nodeRepository.findById(31L)).thenReturn(Optional.of(node(31L, 9L)));
        when(fixture.configRepository.findByNodeId(31L)).thenReturn(Optional.of(config(31L, 3, 99L)));
        when(fixture.jdbc.queryForMap(org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.eq(88L)))
                .thenReturn(Map.of("id", 88L, "emission_subcategory", "PH_HD",
                        "measurement_unit", "GJ", "meter_reading_method", 0,
                        "is_cumulative", 0, "status", 1, "name", "热力采集点"));

        assertThatThrownBy(() -> fixture.controller.factor(31L, 3, 88L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value())
                        .isEqualTo(400));
    }

    private Fixture fixture() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        CollectionScopeService scopes = mock(CollectionScopeService.class);
        CollectionRecordController controller = new CollectionRecordController(
                jdbc, scopes, mock(SystemConfigService.class), mock(EmissionDataFreshnessService.class));
        EmissionNodeRepository nodes = mock(EmissionNodeRepository.class);
        EmissionNodeConfigRepository configs = mock(EmissionNodeConfigRepository.class);
        TemplateRepository templates = mock(TemplateRepository.class);
        EffectiveFactorResolver resolver = mock(EffectiveFactorResolver.class);
        FactorDimensionService dimension = mock(FactorDimensionService.class);
        ReflectionTestUtils.setField(controller, "nodeRepository", nodes);
        ReflectionTestUtils.setField(controller, "nodeConfigRepository", configs);
        ReflectionTestUtils.setField(controller, "templateRepository", templates);
        ReflectionTestUtils.setField(controller, "effectiveFactorResolver", resolver);
        ReflectionTestUtils.setField(controller, "factorDimensionService", dimension);
        return new Fixture(controller, jdbc, scopes, nodes, configs, templates, resolver, dimension);
    }

    private EmissionNode node(long id, long templateId) {
        EmissionNode node = new EmissionNode();
        node.setId(id);
        node.setTemplateId(templateId);
        node.setTypeId(3);
        return node;
    }

    private EmissionNodeConfig config(long nodeId, int pointType, long pointId) {
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setNodeId(nodeId);
        config.setCollectionPointType(pointType);
        config.setCollectionPointId(pointId);
        return config;
    }

    private record Fixture(CollectionRecordController controller,
                           JdbcTemplate jdbc,
                           CollectionScopeService scopes,
                           EmissionNodeRepository nodeRepository,
                           EmissionNodeConfigRepository configRepository,
                           TemplateRepository templateRepository,
                           EffectiveFactorResolver resolver,
                           FactorDimensionService dimension) {
    }
}
