package com.example.carbon.emission.model.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class CollectionScopeAspectTest {
    private final CollectionScopeAspect aspect = new CollectionScopeAspect(
            mock(CollectionScopeService.class), new ObjectMapper());

    @Test
    void classifiesMetersLoadedBySubScopeAsMeters() {
        assertThat(aspect.itemType("getMetersBySubScope")).isEqualTo("meter");
    }

    @Test
    void keepsSubScopeAndScopeListsDistinct() {
        assertThat(aspect.itemType("getSubScopesByScope")).isEqualTo("sub_scope");
        assertThat(aspect.itemType("getAllScopes")).isEqualTo("scope");
    }
}
