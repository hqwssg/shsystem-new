package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.EnergyAttributionStation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface EnergyAttributionStationRepository extends JpaRepository<EnergyAttributionStation, Long> {
    @Query("select s from EnergyAttributionStation s where " +
            "(:keyword is null or :keyword = '' or s.name like concat('%',:keyword,'%') " +
            "or s.pinyinCode like concat('%',:keyword,'%')) and " +
            "(:lineName is null or :lineName = '' or s.lineName = :lineName) and " +
            "(:branchCompany is null or :branchCompany = '' or s.branchCompany = :branchCompany) " +
            "order by s.branchCompany, s.lineName, s.id")
    List<EnergyAttributionStation> search(@Param("keyword") String keyword,
                                           @Param("lineName") String lineName,
                                           @Param("branchCompany") String branchCompany);

    @Query("select count(s) from EnergyAttributionStation s where lower(s.name)=lower(:name) " +
            "and ((s.lineName is null and :lineName is null) or s.lineName=:lineName) " +
            "and ((s.branchCompany is null and :branchCompany is null) or s.branchCompany=:branchCompany) " +
            "and (:excludeId is null or s.id<>:excludeId)")
    long countDuplicate(@Param("name") String name, @Param("lineName") String lineName,
                        @Param("branchCompany") String branchCompany, @Param("excludeId") Long excludeId);
}
