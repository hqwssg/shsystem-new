package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface MonthlyCompanyEnergySummaryRepository extends JpaRepository<MonthlyCompanyEnergySummary, Long> {
    boolean existsByCompanyDeptIdAndYearAndMonth(Long companyDeptId, Integer year, Integer month);
    void deleteByCompanyDeptIdAndYearAndMonth(Long companyDeptId, Integer year, Integer month);
}
