package com.example.carbon.emission.model.service;

import java.util.Collection;
import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;

@Service
public class CollectionPointModelReferenceGuard {
    private final EmissionNodeConfigRepository configs;

    public CollectionPointModelReferenceGuard(EmissionNodeConfigRepository configs) {
        this.configs = configs;
    }

    public void requireNotReferenced(Integer collectionPointType, Long collectionPointId) {
        if (collectionPointId == null) return;
        reject(configs.countByCollectionPointTypeAndCollectionPointId(collectionPointType, collectionPointId));
    }

    public void requireNoneReferenced(Integer collectionPointType, Collection<Long> collectionPointIds) {
        if (collectionPointIds == null || collectionPointIds.isEmpty()) return;
        List<Long> ids = collectionPointIds.stream().filter(java.util.Objects::nonNull).distinct().toList();
        if (ids.isEmpty()) return;
        reject(configs.countByCollectionPointTypeAndCollectionPointIdIn(collectionPointType, ids));
    }

    private void reject(long count) {
        if (count > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "采集点已被" + count + "个模型节点引用，请先在碳排放模型中解除或更换关联后再删除");
        }
    }
}
