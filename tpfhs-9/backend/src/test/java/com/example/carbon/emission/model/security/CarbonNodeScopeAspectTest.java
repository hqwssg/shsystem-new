package com.example.carbon.emission.model.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.when;

import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.Signature;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import com.example.carbon.emission.model.dto.NodeConfigDTO;
import com.example.carbon.emission.model.dto.UpdateNodeRequest;

@ExtendWith(MockitoExtension.class)
class CarbonNodeScopeAspectTest {
    @Mock private CarbonDataScopeService dataScope;
    @Mock private CollectionScopeService collectionScopes;
    @Mock private JoinPoint joinPoint;
    @Mock private Signature signature;

    private CarbonNodeScopeAspect aspect;
    private NodeConfigDTO config;

    @BeforeEach
    void setUp() {
        aspect = new CarbonNodeScopeAspect(dataScope, collectionScopes);
        config = new NodeConfigDTO();
        config.setCollectionPointType(1);
        config.setCollectionPointId(999L);
        UpdateNodeRequest request = new UpdateNodeRequest();
        request.setConfig(config);
        when(joinPoint.getSignature()).thenReturn(signature);
        when(signature.getName()).thenReturn("updateNode");
        when(joinPoint.getArgs()).thenReturn(new Object[] { 30L, request });
    }

    @Test
    void reportsMissingReplacementAsConflict() {
        doThrow(new ResponseStatusException(HttpStatus.NOT_FOUND, "missing"))
                .when(collectionScopes).requireCollectionPoint(1, 999L, false);

        assertThatThrownBy(() -> aspect.check(joinPoint))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> {
                    ResponseStatusException response = (ResponseStatusException) error;
                    assertThat(response.getStatusCode().value()).isEqualTo(409);
                    assertThat(response.getReason()).contains("重新选择有效采集点");
                });
    }

    @Test
    void preservesForbiddenForExistingOutOfScopePoint() {
        doThrow(new ResponseStatusException(HttpStatus.FORBIDDEN, "denied"))
                .when(collectionScopes).requireCollectionPoint(1, 999L, false);

        assertThatThrownBy(() -> aspect.check(joinPoint))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(
                        ((ResponseStatusException) error).getStatusCode().value()).isEqualTo(403));
    }
}
