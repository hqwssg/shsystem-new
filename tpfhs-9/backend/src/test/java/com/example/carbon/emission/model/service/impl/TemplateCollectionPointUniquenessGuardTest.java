package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class TemplateCollectionPointUniquenessGuardTest {

    @Mock TemplateRepository templates;
    @Mock EmissionNodeRepository nodes;
    @Mock EmissionNodeConfigRepository configs;
    TemplateCollectionPointUniquenessGuard guard;

    @BeforeEach
    void setUp() {
        guard = new TemplateCollectionPointUniquenessGuard(templates, nodes, configs);
    }

    @Test
    void rejectsTheSamePhysicalPointInsideOneTemplate() {
        when(nodes.findByTemplateId(20L)).thenReturn(List.of(node(10L, 20L, "节点甲"), node(11L, 20L, "节点乙")));
        when(configs.findCollectionPointConfigsByTemplateId(20L)).thenReturn(List.of(config(10L, 1, 36L), config(11L, 1, 36L)));

        assertThatThrownBy(() -> guard.requireUnique(20L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value()).isEqualTo(409))
                .hasMessageContaining("节点甲").hasMessageContaining("节点乙");
    }

    @Test
    void allowsTheSamePhysicalPointInDifferentTemplates() {
        when(nodes.findByTemplateId(20L)).thenReturn(List.of(node(10L, 20L, "模板一节点")));
        when(configs.findCollectionPointConfigsByTemplateId(20L)).thenReturn(List.of(config(10L, 1, 36L)));

        assertThatCode(() -> guard.requireUnique(20L)).doesNotThrowAnyException();
    }

    @Test
    void saveCheckLocksTemplateAndRejectsAnotherNode() {
        EmissionNode target = node(11L, 20L, "目标节点");
        when(nodes.findById(11L)).thenReturn(Optional.of(target));
        when(templates.findForCompanyUpdate(20L)).thenReturn(Optional.of(new Template()));
        when(nodes.findByTemplateId(20L)).thenReturn(List.of(node(10L, 20L, "已关联节点"), target));
        when(configs.findCollectionPointConfigsByTemplateId(20L)).thenReturn(List.of(config(10L, 1, 36L)));

        assertThatThrownBy(() -> guard.requireAvailableForSave(11L, 1, 36L))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("已关联节点");
    }

    private EmissionNode node(long id, long templateId, String name) {
        EmissionNode node = new EmissionNode();
        node.setId(id); node.setTemplateId(templateId); node.setName(name); node.setTypeId(3);
        return node;
    }

    private EmissionNodeConfig config(long nodeId, int type, long pointId) {
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setNodeId(nodeId); config.setCollectionPointType(type); config.setCollectionPointId(pointId);
        return config;
    }
}
