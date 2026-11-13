package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface MonthlyCalcNodeSummaryRepository extends JpaRepository<MonthlyCalcNodeSummary, Long> {
    java.util.List<MonthlyCalcNodeSummary> findByTemplateIdAndYearAndMonth(Long templateId, Integer year, Integer month);
    void deleteByTemplateIdAndYearAndMonth(Long templateId, Integer year, Integer month);
}
