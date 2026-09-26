package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.repository.EmissionNodeInfoRepository;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

/** 解析节点在一次核算中的有效纳入状态，并校验设计树不存在孤儿或循环。 */
@Service
public class NodeInclusionResolver {

    private static final int TYPE_ID_CALCULATION = 2;

    private final EmissionNodeInfoRepository nodeInfoRepository;

    public NodeInclusionResolver(EmissionNodeInfoRepository nodeInfoRepository) {
        this.nodeInfoRepository = nodeInfoRepository;
    }

    public Map<Long, InclusionDecision> resolve(List<EmissionNode> nodes) {
        Map<Long, EmissionNode> byId;
        try {
            byId = nodes.stream().collect(Collectors.toMap(EmissionNode::getId, Function.identity()));
        } catch (IllegalStateException ex) {
            throw new IllegalStateException("模版节点树包含重复节点", ex);
        }
        Map<Long, InclusionDecision> decisions = new HashMap<>();
        for (EmissionNode node : nodes) {
            resolveOne(node.getId(), byId, decisions, new HashSet<>());
        }
        return decisions;
    }

    private InclusionDecision resolveOne(
            Long nodeId, Map<Long, EmissionNode> byId,
            Map<Long, InclusionDecision> decisions, Set<Long> visiting) {
        InclusionDecision cached = decisions.get(nodeId);
        if (cached != null) {
            return cached;
        }
        if (!visiting.add(nodeId)) {
            throw new IllegalStateException("模版节点树存在循环父子关系，nodeId=" + nodeId);
        }
        EmissionNode node = byId.get(nodeId);
        if (node == null) {
            throw new IllegalStateException("模版节点树引用不存在的节点，nodeId=" + nodeId);
        }

        InclusionDecision parentDecision = new InclusionDecision(true, null);
        if (node.getParentId() != null) {
            if (!byId.containsKey(node.getParentId())) {
                throw new IllegalStateException("模版节点树存在孤儿节点，nodeId=" + nodeId
                        + ", parentId=" + node.getParentId());
            }
            parentDecision = resolveOne(node.getParentId(), byId, decisions, visiting);
        }

        boolean configuredIncluded = true;
        if (node.getTypeId() != null && node.getTypeId() == TYPE_ID_CALCULATION) {
            configuredIncluded = nodeInfoRepository.findByNodeId(nodeId)
                    .map(info -> !Boolean.FALSE.equals(info.getIncludeInCalculation()))
                    .orElse(true);
        }
        InclusionDecision decision;
        if (!parentDecision.included()) {
            decision = new InclusionDecision(false, parentDecision.excludedByNodeId());
        } else if (!configuredIncluded) {
            decision = new InclusionDecision(false, nodeId);
        } else {
            decision = new InclusionDecision(true, null);
        }
        visiting.remove(nodeId);
        decisions.put(nodeId, decision);
        return decision;
    }

    public record InclusionDecision(boolean included, Long excludedByNodeId) {}
}
