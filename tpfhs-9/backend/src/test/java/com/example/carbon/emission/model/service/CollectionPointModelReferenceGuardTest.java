package com.example.carbon.emission.model.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.server.ResponseStatusException;

import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;

@ExtendWith(MockitoExtension.class)
class CollectionPointModelReferenceGuardTest {
    @Mock private EmissionNodeConfigRepository configs;

    @Test
    void blocksSingleReferencedCollectionPointWithConflict() {
        when(configs.countByCollectionPointTypeAndCollectionPointId(1, 9L)).thenReturn(2L);
        CollectionPointModelReferenceGuard guard = new CollectionPointModelReferenceGuard(configs);

        assertThatThrownBy(() -> guard.requireNotReferenced(1, 9L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> {
                    ResponseStatusException response = (ResponseStatusException) error;
                    assertThat(response.getStatusCode().value()).isEqualTo(409);
                    assertThat(response.getReason()).contains("2个模型节点引用");
                });
    }

    @Test
    void blocksAncestorDeletionBeforeAnyDescendantCanBeDeleted() {
        when(configs.countByCollectionPointTypeAndCollectionPointIdIn(2, List.of(7L, 8L))).thenReturn(1L);
        CollectionPointModelReferenceGuard guard = new CollectionPointModelReferenceGuard(configs);

        assertThatThrownBy(() -> guard.requireNoneReferenced(2, List.of(7L, 8L)))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value()).isEqualTo(409));
    }

    @Test
    void allowsUnreferencedCollectionPoints() {
        when(configs.countByCollectionPointTypeAndCollectionPointIdIn(3, List.of(7L, 8L))).thenReturn(0L);
        CollectionPointModelReferenceGuard guard = new CollectionPointModelReferenceGuard(configs);

        assertThatCode(() -> guard.requireNoneReferenced(3, List.of(7L, 8L, 8L))).doesNotThrowAnyException();
    }
}
