package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface MonthlyCollectionNodeDataRepository extends JpaRepository<MonthlyCollectionNodeData, Long> {
    java.util.Optional<MonthlyCollectionNodeData> findByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(
            Integer collectionPointType, Long collectionPointId, Integer year, Integer month);
    void deleteByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(
            Integer collectionPointType, Long collectionPointId, Integer year, Integer month);
}
