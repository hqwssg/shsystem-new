package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.Collection;
import java.util.List;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

@Repository
public interface EmissionNodeConfigRepository extends JpaRepository<EmissionNodeConfig, Long> {
    
    Optional<EmissionNodeConfig> findByNodeId(Long nodeId);
    
    void deleteByNodeId(Long nodeId);

    long countByCollectionPointTypeAndCollectionPointId(Integer collectionPointType, Long collectionPointId);

    long countByCollectionPointTypeAndCollectionPointIdIn(Integer collectionPointType,
            Collection<Long> collectionPointIds);

    @Query("select c from EmissionNodeConfig c join EmissionNode n on n.id=c.nodeId "
            + "where n.templateId=:templateId and c.collectionPointType is not null "
            + "and c.collectionPointId is not null")
    List<EmissionNodeConfig> findCollectionPointConfigsByTemplateId(@Param("templateId") Long templateId);
}
