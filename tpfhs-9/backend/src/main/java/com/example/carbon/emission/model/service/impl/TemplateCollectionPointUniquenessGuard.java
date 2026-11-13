package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.*;

/** 保证一个核算模板内同一物理采集点只关联一个节点。 */
@Service
public class TemplateCollectionPointUniquenessGuard {

    private final TemplateRepository templates;
    private final EmissionNodeRepository nodes;
    private final EmissionNodeConfigRepository configs;

    public TemplateCollectionPointUniquenessGuard(TemplateRepository templates,
                                                  EmissionNodeRepository nodes,
                                                  EmissionNodeConfigRepository configs) {
        this.templates = templates;
        this.nodes = nodes;
        this.configs = configs;
    }

    public void requireAvailableForSave(Long nodeId, Integer type, Long pointId) {
        if (type == null || pointId == null) return;
        EmissionNode target = nodes.findById(nodeId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "节点不存在: " + nodeId));
        templates.findForCompanyUpdate(target.getTemplateId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "模版不存在: " + target.getTemplateId()));
        Optional<Conflict> conflict = conflicts(target.getTemplateId()).stream()
                .filter(item -> item.type().equals(type) && item.pointId().equals(pointId))
                .filter(item -> item.nodes().stream().anyMatch(node -> !node.id().equals(nodeId)))
                .findFirst();
        if (conflict.isPresent()) {
            NodeRef other = conflict.get().nodes().stream()
                    .filter(node -> !node.id().equals(nodeId)).findFirst().orElseThrow();
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "同一核算模版内物理采集点不能重复引用：type=" + type + ", id=" + pointId
                            + "，已关联节点「" + other.name() + "」");
        }
    }

    public void requireUnique(Long templateId) {
        List<Conflict> duplicates = findDuplicates(templateId);
        if (!duplicates.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, message(duplicates.get(0)));
        }
    }

    public List<Conflict> findDuplicates(Long templateId) {
        return conflicts(templateId).stream().filter(item -> item.nodes().size() > 1).toList();
    }

    public String message(Conflict conflict) {
        return "同一核算模版重复引用物理采集点：type=" + conflict.type() + ", id=" + conflict.pointId()
                + "，冲突节点=" + conflict.nodes().stream().map(NodeRef::name).toList();
    }

    private List<Conflict> conflicts(Long templateId) {
        Map<Long, EmissionNode> nodeMap = new HashMap<>();
        nodes.findByTemplateId(templateId).forEach(node -> nodeMap.put(node.getId(), node));
        Map<PointKey, List<NodeRef>> grouped = new LinkedHashMap<>();
        for (EmissionNodeConfig config : configs.findCollectionPointConfigsByTemplateId(templateId)) {
            EmissionNode node = nodeMap.get(config.getNodeId());
            if (node == null) continue;
            PointKey key = new PointKey(config.getCollectionPointType(), config.getCollectionPointId());
            grouped.computeIfAbsent(key, ignored -> new ArrayList<>())
                    .add(new NodeRef(node.getId(), node.getName() == null ? String.valueOf(node.getId()) : node.getName()));
        }
        return grouped.entrySet().stream()
                .map(entry -> new Conflict(entry.getKey().type(), entry.getKey().pointId(), List.copyOf(entry.getValue())))
                .toList();
    }

    private record PointKey(Integer type, Long pointId) {}
    public record NodeRef(Long id, String name) {}
    public record Conflict(Integer type, Long pointId, List<NodeRef> nodes) {}
}
