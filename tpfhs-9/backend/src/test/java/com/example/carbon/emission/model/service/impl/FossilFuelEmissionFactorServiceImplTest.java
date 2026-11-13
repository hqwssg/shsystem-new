package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.FossilFuelEmissionFactorDTO;
import com.example.carbon.emission.model.entity.FossilFuelEmissionFactor;
import com.example.carbon.emission.model.repository.FossilFuelEmissionFactorRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class FossilFuelEmissionFactorServiceImplTest {

    @Mock
    private FossilFuelEmissionFactorRepository repository;

    @InjectMocks
    private FossilFuelEmissionFactorServiceImpl service;

    @Test
    void allowsDifferentFactorNamesForTheSameFuelType() {
        FossilFuelEmissionFactorDTO dto = factor("运输天然气因子", "天然气");
        when(repository.existsByEmissionFactorName(dto.getEmissionFactorName())).thenReturn(false);
        when(repository.save(any(FossilFuelEmissionFactor.class))).thenAnswer(invocation -> {
            FossilFuelEmissionFactor entity = invocation.getArgument(0);
            entity.setId(7L);
            return entity;
        });

        FossilFuelEmissionFactorDTO saved = service.create(dto);

        assertThat(saved.getId()).isEqualTo(7L);
        assertThat(saved.getFuelType()).isEqualTo("天然气");
        assertThat(saved.getUnit()).isEqualTo("m3");
        assertThat(saved.getFactorUnit()).isEqualTo("tCO₂/m³");
        verify(repository, never()).existsByEmissionFactorNameAndIdNot(any(), anyLong());
    }

    @Test
    void rejectsDuplicateFactorNameWithConflictWithoutSaving() {
        FossilFuelEmissionFactorDTO dto = factor("天然气排放因子", "天然气");
        when(repository.existsByEmissionFactorName(dto.getEmissionFactorName())).thenReturn(true);

        assertThatThrownBy(() -> service.create(dto))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode())
                        .isEqualTo(HttpStatus.CONFLICT))
                .hasMessageContaining("名称已存在");
        verify(repository, never()).save(any());
    }

    @Test
    void rejectsDuplicateNameOnUpdateWithoutChangingStoredEntity() {
        FossilFuelEmissionFactor existing = new FossilFuelEmissionFactor();
        existing.setId(9L);
        existing.setEmissionFactorName("原名称");
        existing.setFuelType("天然气");
        FossilFuelEmissionFactorDTO dto = factor("重复名称", "天然气");
        when(repository.findById(9L)).thenReturn(Optional.of(existing));
        when(repository.existsByEmissionFactorNameAndIdNot("重复名称", 9L)).thenReturn(true);

        assertThatThrownBy(() -> service.update(9L, dto))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode())
                        .isEqualTo(HttpStatus.CONFLICT));
        assertThat(existing.getEmissionFactorName()).isEqualTo("原名称");
        verify(repository, never()).save(any());
    }

    @Test
    void returnsAllFactorsForFuelTypeAndDeterministicLegacyFirst() {
        FossilFuelEmissionFactor first = entity(1L, "天然气因子A", "天然气");
        FossilFuelEmissionFactor second = entity(2L, "天然气因子B", "天然气");
        when(repository.findAllByFuelTypeOrderByIdAsc("天然气")).thenReturn(List.of(first, second));
        when(repository.findFirstByFuelTypeOrderByIdAsc("天然气")).thenReturn(Optional.of(first));

        assertThat(service.findAllByFuelType("天然气"))
                .extracting(FossilFuelEmissionFactorDTO::getEmissionFactorName)
                .containsExactly("天然气因子A", "天然气因子B");
        assertThat(service.findByFuelType("天然气").getId()).isEqualTo(1L);
    }

    @Test
    void normalizesEverySupportedUnitAndDerivesFactorUnit() {
        assertRule("烟煤", "吨(t)", "t", "tCO₂/t");
        assertRule("烟煤", "kg", "kg", "tCO₂/kg");
        assertRule("烟煤", "g", "g", "tCO₂/g");
        assertRule("汽油", "L", "L", "tCO₂/L");
        assertRule("天然气", "立方米(m³)", "m3", "tCO₂/m³");
        assertRule("天然气", "万m³", "wan_m3", "tCO₂/万m³");
        assertRule("天然气", "Nm3", "Nm3", "tCO₂/Nm³");
        assertRule("天然气", "104 Nm3", "wan_Nm3", "tCO₂/万Nm³");
    }

    @Test
    void rejectsIncompatibleUnitBeforeChangingStoredEntity() {
        FossilFuelEmissionFactor existing = entity(9L, "天然气因子", "天然气");
        existing.setUnit("m3");
        existing.setFactorUnit("tCO₂/m³");
        FossilFuelEmissionFactorDTO dto = factor("天然气因子", "天然气");
        dto.setUnit("t");

        assertThatThrownBy(() -> service.update(9L, dto))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode())
                        .isEqualTo(HttpStatus.BAD_REQUEST))
                .hasMessageContaining("不支持计量单位");
        assertThat(existing.getUnit()).isEqualTo("m3");
        assertThat(existing.getFactorUnit()).isEqualTo("tCO₂/m³");
        verify(repository, never()).findById(anyLong());
        verify(repository, never()).save(any());
    }

    private void assertRule(String fuelType, String inputUnit, String expectedUnit, String expectedFactorUnit) {
        FossilFuelEmissionFactorDTO dto = factor("测试因子-" + inputUnit, fuelType);
        dto.setUnit(inputUnit);
        when(repository.existsByEmissionFactorName(dto.getEmissionFactorName())).thenReturn(false);
        when(repository.save(any(FossilFuelEmissionFactor.class))).thenAnswer(invocation -> invocation.getArgument(0));

        FossilFuelEmissionFactorDTO saved = service.create(dto);

        assertThat(saved.getUnit()).isEqualTo(expectedUnit);
        assertThat(saved.getFactorUnit()).isEqualTo(expectedFactorUnit);
    }

    private FossilFuelEmissionFactorDTO factor(String name, String fuelType) {
        FossilFuelEmissionFactorDTO dto = new FossilFuelEmissionFactorDTO();
        dto.setEmissionFactorName(name);
        dto.setFuelType(fuelType);
        dto.setUnit("m3");
        dto.setEmissionFactor(new BigDecimal("2.100000"));
        return dto;
    }

    private FossilFuelEmissionFactor entity(Long id, String name, String fuelType) {
        FossilFuelEmissionFactor entity = new FossilFuelEmissionFactor();
        entity.setId(id);
        entity.setEmissionFactorName(name);
        entity.setFuelType(fuelType);
        entity.setEmissionFactor(new BigDecimal("2.100000"));
        return entity;
    }
}
