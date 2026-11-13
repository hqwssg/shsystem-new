package com.example.carbon.emission.model.security;

import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import com.example.carbon.emission.model.dto.CreateNodeRequest;
import com.example.carbon.emission.model.dto.UpdateNodeRequest;

@Aspect
@Component
public class CarbonNodeScopeAspect {
    private final CarbonDataScopeService dataScope;
    private final CollectionScopeService collectionScopes;

    public CarbonNodeScopeAspect(CarbonDataScopeService dataScope, CollectionScopeService collectionScopes) {
        this.dataScope = dataScope;
        this.collectionScopes = collectionScopes;
    }

    @Before("execution(public * com.example.carbon.emission.model.controller.EmissionNodeController.*(..))")
    public void check(JoinPoint joinPoint) {
        String method = joinPoint.getSignature().getName();
        Object[] args = joinPoint.getArgs();
        for (Object arg : args) {
            if (arg instanceof com.example.carbon.emission.model.dto.NodeConfigDTO config
                    && config.getCollectionPointId() != null) {
                requireValidReplacement(config);
            }
            if (arg instanceof UpdateNodeRequest request && request.getConfig() != null
                    && request.getConfig().getCollectionPointId() != null) {
                requireValidReplacement(request.getConfig());
            }
        }
        boolean write = method.startsWith("create") || method.startsWith("update") || method.startsWith("delete")
                || method.startsWith("move") || method.startsWith("mount");

        if ("getAllNodes".equals(method) && !dataScope.current().allData()) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.FORBIDDEN, "Select an authorized template first");
        }

        if ("getTree".equals(method)) {
            if (args.length > 0 && args[0] instanceof Long templateId) {
                dataScope.requireTemplate(templateId, false);
                return;
            }
            if (!dataScope.current().allData()) {
                throw new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.FORBIDDEN, "Select an authorized template first");
            }
        }
        if ("createNode".equals(method) && args.length > 0 && args[0] instanceof CreateNodeRequest request) {
            if (request.getParentId() != null) dataScope.requireNode(request.getParentId(), true);
            else if (request.getTemplateId() != null) dataScope.requireTemplate(request.getTemplateId(), true);
            return;
        }
        if (args.length > 0 && args[0] instanceof Long nodeId && !"getNextNodeId".equals(method)) {
            if (method.startsWith("delete")) {
                dataScope.requireNodeTreeAllowMissingCollectionPoint(nodeId, write);
            } else if (method.startsWith("update") || "getNodeById".equals(method)
                    || "getNodeConfig".equals(method)) {
                dataScope.requireNodeAllowMissingCollectionPoint(nodeId, write);
            } else if (method.startsWith("move") || method.startsWith("mount")) {
                dataScope.requireNodeTree(nodeId, write);
            } else {
                dataScope.requireNode(nodeId, write);
            }
        }
        if ("mountNodeTemplate".equals(method) && args.length > 1 && args[1] instanceof java.util.Map<?, ?> body
                && body.get("templateId") instanceof Long templateId) {
            dataScope.requireTemplateTree(templateId);
        }
    }

    private void requireValidReplacement(com.example.carbon.emission.model.dto.NodeConfigDTO config) {
        try {
            collectionScopes.requireCollectionPoint(config.getCollectionPointType(),
                    config.getCollectionPointId(), false);
        } catch (ResponseStatusException ex) {
            if (ex.getStatusCode().value() == HttpStatus.NOT_FOUND.value()) {
                throw new ResponseStatusException(HttpStatus.CONFLICT,
                        "所选采集点已不存在，请重新选择有效采集点", ex);
            }
            throw ex;
        }
    }
}
