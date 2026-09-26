package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.EmissionFactorTemplate;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

@Repository
public interface EmissionFactorTemplateRepository extends JpaRepository<EmissionFactorTemplate, Long> {

    List<EmissionFactorTemplate> findAllByOrderByCreatedAtDesc();

    @Query("select t from EmissionFactorTemplate t where t.isShared = 1 or t.createdBy = :userId order by t.createdAt desc")
    List<EmissionFactorTemplate> findVisibleTo(@Param("userId") Long userId);

    List<EmissionFactorTemplate> findByStatusOrderByCreatedAtDesc(Integer status);

    boolean existsByTemplateName(String templateName);
}
