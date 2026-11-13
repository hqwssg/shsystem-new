package com.example.carbon.emission.model.security;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Optional;
import java.util.Set;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
import org.springframework.web.server.ResponseStatusException;

import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;

@ExtendWith(MockitoExtension.class)
class CarbonDataScopeOrphanNodeTest {
    @Mock private TemplateRepository templates;
    @Mock private EmissionNodeRepository nodes;
    @Mock private CollectionScopeService collectionScopes;
    @Mock private EmissionNodeConfigRepository configs;
    private CarbonDataScopeService service;

    @BeforeEach
    void setUp() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute(CarbonSecurityContext.REQUEST_ATTRIBUTE,
                new CarbonSecurityContext(1L, "tester", "测试", 10L, "department", Set.of(), Set.of(),
                        false, false, List.of(10L), List.of()));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        service = new CarbonDataScopeService(templates, nodes, collectionScopes, configs);
        Template template = new Template();
        template.setId(20L);
        template.setDeptId(10L);
        EmissionNode node = new EmissionNode();
        node.setId(30L);
        node.setTemplateId(20L);
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setNodeId(30L);
        config.setCollectionPointType(1);
        config.setCollectionPointId(999L);
        when(templates.findById(20L)).thenReturn(Optional.of(template));
        when(nodes.findById(30L)).thenReturn(Optional.of(node));
        when(configs.findByNodeId(30L)).thenReturn(Optional.of(config));
    }

    @AfterEach
    void tearDown() {
        RequestContextHolder.resetRequestAttributes();
    }

    @Test
    void allowsRepairOrDeleteOnlyWhenOldCollectionPointIsMissing() {
        doThrow(new ResponseStatusException(HttpStatus.NOT_FOUND, "missing"))
                .when(collectionScopes).requireCollectionPoint(1, 999L, false);

        assertThatCode(() -> service.requireNodeAllowMissingCollectionPoint(30L, true)).doesNotThrowAnyException();
        assertThatThrownBy(() -> service.requireNode(30L, true)).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void doesNotTreatUnauthorizedExistingPointAsAnOrphan() {
        doThrow(new ResponseStatusException(HttpStatus.FORBIDDEN, "denied"))
                .when(collectionScopes).requireCollectionPoint(1, 999L, false);

        assertThatThrownBy(() -> service.requireNodeAllowMissingCollectionPoint(30L, true))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> org.assertj.core.api.Assertions.assertThat(
                        ((ResponseStatusException) error).getStatusCode().value()).isEqualTo(403));
    }
}
