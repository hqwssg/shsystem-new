package com.example.carbon.emission.model.repository;

import com.example.carbon.emission.model.entity.FossilFuelEmissionFactor;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface FossilFuelEmissionFactorRepository extends JpaRepository<FossilFuelEmissionFactor, Long> {
    
    Optional<FossilFuelEmissionFactor> findFirstByFuelTypeOrderByIdAsc(String fuelType);
    
    List<FossilFuelEmissionFactor> findAllByFuelTypeOrderByIdAsc(String fuelType);
    
    List<FossilFuelEmissionFactor> findByFuelTypeContaining(String fuelType);
    
    boolean existsByEmissionFactorName(String emissionFactorName);

    boolean existsByEmissionFactorNameAndIdNot(String emissionFactorName, Long id);
}
