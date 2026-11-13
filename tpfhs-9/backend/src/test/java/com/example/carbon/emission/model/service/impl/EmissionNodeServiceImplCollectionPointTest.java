package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.NodeConfigDTO;
import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.MeterInfo;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeInfoRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.FossilFuelMeterInfoRepository;
import com.example.carbon.emission.model.repository.MeterInfoRepository;
import com.example.carbon.emission.model.repository.NodeTypeRepository;
import com.example.carbon.emission.model.repository.PurchasedHeatMeterInfoRepository;
import com.example.carbon.emission.model.repository.SystemConfigRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.server.ResponseStatusException;

import java.util.Optional;
import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EmissionNodeServiceImplCollectionPointTest {

    @Mock private EmissionNodeRepository nodeRepository;
    @Mock private EmissionNodeConfigRepository configRepository;
    @Mock private NodeTypeRepository typeRepository;
    @Mock private TemplateRepository templateRepository;
    @Mock private EmissionNodeInfoRepository nodeInfoRepository;
    @Mock private SystemConfigRepository systemConfigRepository;
    @Mock private MeterInfoRepository meterInfoRepository;
    @Mock private FossilFuelMeterInfoRepository fossilFuelMeterInfoRepository;
    @Mock private PurchasedHeatMeterInfoRepository purchasedHeatMeterInfoRepository;
    @Mock private FactorDimensionService factorDimensionService;
    @Mock private EffectiveFactorResolver effectiveFactorResolver;
    @Mock private TemplateCollectionPointUniquenessGuard collectionPointUniquenessGuard;

    @InjectMocks
    private EmissionNodeServiceImpl service;

    @Test
    void rejectsMissingCollectionPointWithoutChangingConfig() {
        NodeConfigDTO dto = point(2, 9999L, "化石燃料", "柴油");
        when(fossilFuelMeterInfoRepository.findById(9999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.updateNodeConfig(10L, dto, 1L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value())
                        .isEqualTo(422));
        verify(configRepository, never()).save(any());
    }

    @Test
    void rejectsMismatchedSubcategoryWithoutChangingConfig() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(factorDimensionService.resolveSubcategoryCode("柴油")).thenReturn("FF_D");
        when(factorDimensionService.resolveSubcategoryCode("外购电力")).thenReturn("PE_PF");
        NodeConfigDTO dto = point(1, 8L, "购入的电力", "柴油");

        assertThatThrownBy(() -> service.updateNodeConfig(10L, dto, 1L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value())
                        .isEqualTo(422));
        verify(configRepository, never()).save(any());
    }

    @Test
    void fillsBlankCategoriesFromValidCollectionPoint() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(configRepository.findByNodeId(10L)).thenReturn(Optional.empty());
        when(configRepository.save(any(EmissionNodeConfig.class))).thenAnswer(invocation -> invocation.getArgument(0));
        NodeConfigDTO dto = point(1, 8L, null, null);

        service.updateNodeConfig(10L, dto, 1L);

        ArgumentCaptor<EmissionNodeConfig> saved = ArgumentCaptor.forClass(EmissionNodeConfig.class);
        verify(configRepository).save(saved.capture());
        assertThat(saved.getValue().getEmissionCategory()).isEqualTo("购入的电力");
        assertThat(saved.getValue().getEmissionSubcategory()).isEqualTo("外购电力");
    }

    @Test
    void rejectsPartialFactorOverrideWithoutChangingConfig() {
        NodeConfigDTO dto = point(1, 8L, "购入的电力", "外购电力");
        dto.setCarbonEmissionFactor(new BigDecimal("0.5"));

        assertThatThrownBy(() -> service.updateNodeConfig(10L, dto, 1L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value())
                        .isEqualTo(400));
        verify(configRepository, never()).save(any());
    }

    @Test
    void clearsDescriptionWhenFactorOverrideIsRemoved() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(factorDimensionService.resolveSubcategoryCode("外购电力")).thenReturn("PE_PF");
        when(configRepository.findByNodeId(10L)).thenReturn(Optional.empty());
        when(configRepository.save(any(EmissionNodeConfig.class))).thenAnswer(invocation -> invocation.getArgument(0));
        NodeConfigDTO dto = point(1, 8L, "购入的电力", "外购电力");
        dto.setCarbonEmissionFactorDescription("不应单独保留");

        service.updateNodeConfig(10L, dto, 1L);

        ArgumentCaptor<EmissionNodeConfig> saved = ArgumentCaptor.forClass(EmissionNodeConfig.class);
        verify(configRepository).save(saved.capture());
        assertThat(saved.getValue().getCarbonEmissionFactor()).isNull();
        assertThat(saved.getValue().getCarbonEmissionFactorUnit()).isNull();
        assertThat(saved.getValue().getCarbonEmissionFactorDescription()).isNull();
        assertThat(saved.getValue().getCarbonEmissionFactorSource()).isNull();
        assertThat(saved.getValue().getCarbonEmissionFactorId()).isNull();
    }

    @Test
    void freezesFormalFactorReferenceAndDqiForNewCollectionNodeOverride() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(factorDimensionService.resolveSubcategoryCode("外购电力")).thenReturn("PE_PF");
        when(configRepository.findByNodeId(10L)).thenReturn(Optional.empty());
        EmissionNode node = new EmissionNode();
        node.setId(10L);
        node.setTypeId(3);
        when(nodeRepository.findById(10L)).thenReturn(Optional.of(node));
        when(effectiveFactorResolver.resolveReference("ELECTRICITY", 31L))
                .thenReturn(new EffectiveFactorResolver.FactorReference("ELECTRICITY", 31L,
                        "2025正式电力因子", new EffectiveFactorResolver.FactorDqiSnapshot(
                                5, 5, 4, null, 2025, 5, 5)));
        when(configRepository.save(any(EmissionNodeConfig.class))).thenAnswer(invocation -> invocation.getArgument(0));

        NodeConfigDTO dto = point(1, 8L, "购入的电力", "外购电力");
        dto.setCarbonEmissionFactor(new BigDecimal("0.53"));
        dto.setCarbonEmissionFactorUnit("kgCO₂/kWh");
        dto.setCarbonEmissionFactorSource("ELECTRICITY");
        dto.setCarbonEmissionFactorId(31L);

        service.updateNodeConfig(10L, dto, 1L);

        ArgumentCaptor<EmissionNodeConfig> saved = ArgumentCaptor.forClass(EmissionNodeConfig.class);
        verify(configRepository).save(saved.capture());
        assertThat(saved.getValue().getCarbonEmissionFactorName()).isEqualTo("2025正式电力因子");
        assertThat(saved.getValue().getCarbonEmissionFactorDqiE1Score()).isEqualTo(5);
        assertThat(saved.getValue().getCarbonEmissionFactorDataYear()).isEqualTo(2025);
    }

    @Test
    void legacyOverrideWithoutFormalReferenceMustBeReselected() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(factorDimensionService.resolveSubcategoryCode("外购电力")).thenReturn("PE_PF");
        EmissionNodeConfig existing = new EmissionNodeConfig();
        existing.setNodeId(10L);
        existing.setCarbonEmissionFactor(new BigDecimal("0.53"));
        existing.setCarbonEmissionFactorUnit("kgCO₂/kWh");
        when(configRepository.findByNodeId(10L)).thenReturn(Optional.of(existing));
        EmissionNode node = new EmissionNode();
        node.setId(10L);
        node.setTypeId(3);
        when(nodeRepository.findById(10L)).thenReturn(Optional.of(node));
        NodeConfigDTO dto = point(1, 8L, "购入的电力", "外购电力");
        dto.setCarbonEmissionFactor(new BigDecimal("0.53"));
        dto.setCarbonEmissionFactorUnit("kgCO₂/kWh");

        assertThatThrownBy(() -> service.updateNodeConfig(10L, dto, 1L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value())
                        .isEqualTo(422))
                .hasMessageContaining("重新选择有效因子");
        verify(configRepository, never()).save(any());
    }

    @Test
    void ordinaryEditKeepsThePreviouslyFrozenSnapshotForTheSameReference() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(factorDimensionService.resolveSubcategoryCode("外购电力")).thenReturn("PE_PF");
        EmissionNodeConfig existing = completeOverride(10L, "0.53", 31L, 5);
        when(configRepository.findByNodeId(10L)).thenReturn(Optional.of(existing));
        EmissionNode node = new EmissionNode();
        node.setId(10L);
        node.setTypeId(3);
        when(nodeRepository.findById(10L)).thenReturn(Optional.of(node));
        when(configRepository.save(any(EmissionNodeConfig.class))).thenAnswer(invocation -> invocation.getArgument(0));

        NodeConfigDTO dto = point(1, 8L, "购入的电力", "外购电力");
        dto.setCarbonEmissionFactor(new BigDecimal("0.99"));
        dto.setCarbonEmissionFactorUnit("tCO₂/MWh");
        dto.setCarbonEmissionFactorDescription("客户端不应改写冻结快照");
        dto.setCarbonEmissionFactorSource("ELECTRICITY");
        dto.setCarbonEmissionFactorId(31L);

        service.updateNodeConfig(10L, dto, 1L);

        assertThat(existing.getCarbonEmissionFactor()).isEqualByComparingTo("0.53");
        assertThat(existing.getCarbonEmissionFactorUnit()).isEqualTo("kgCO₂/kWh");
        assertThat(existing.getCarbonEmissionFactorDqiE1Score()).isEqualTo(5);
        verify(effectiveFactorResolver, never()).resolveReference(any(), any());
    }

    @Test
    void explicitReselectionRefreshesTheWholeSnapshotEvenForTheSameReference() {
        MeterInfo meter = meter(8L, "外购电力");
        when(meterInfoRepository.findById(8L)).thenReturn(Optional.of(meter));
        when(factorDimensionService.resolveSubcategoryCode("外购电力")).thenReturn("PE_PF");
        EmissionNodeConfig existing = completeOverride(10L, "0.53", 31L, 5);
        when(configRepository.findByNodeId(10L)).thenReturn(Optional.of(existing));
        EmissionNode node = new EmissionNode();
        node.setId(10L);
        node.setTypeId(3);
        when(nodeRepository.findById(10L)).thenReturn(Optional.of(node));
        when(effectiveFactorResolver.resolveReference("ELECTRICITY", 31L))
                .thenReturn(new EffectiveFactorResolver.FactorReference("ELECTRICITY", 31L,
                        "更新后的正式因子", new EffectiveFactorResolver.FactorDqiSnapshot(
                                3, 4, 4, null, 2026, 4, 5)));
        when(configRepository.save(any(EmissionNodeConfig.class))).thenAnswer(invocation -> invocation.getArgument(0));

        NodeConfigDTO dto = point(1, 8L, "购入的电力", "外购电力");
        dto.setCarbonEmissionFactor(new BigDecimal("0.60"));
        dto.setCarbonEmissionFactorUnit("tCO₂/MWh");
        dto.setCarbonEmissionFactorDescription("重新选择后的完整快照");
        dto.setCarbonEmissionFactorSource("ELECTRICITY");
        dto.setCarbonEmissionFactorId(31L);
        dto.setCarbonEmissionFactorReselected(true);

        service.updateNodeConfig(10L, dto, 1L);

        assertThat(existing.getCarbonEmissionFactor()).isEqualByComparingTo("0.60");
        assertThat(existing.getCarbonEmissionFactorUnit()).isEqualTo("tCO₂/MWh");
        assertThat(existing.getCarbonEmissionFactorName()).isEqualTo("更新后的正式因子");
        assertThat(existing.getCarbonEmissionFactorDqiE1Score()).isEqualTo(3);
        assertThat(existing.getCarbonEmissionFactorDataYear()).isEqualTo(2026);
    }

    private NodeConfigDTO point(int type, long id, String category, String subcategory) {
        NodeConfigDTO dto = new NodeConfigDTO();
        dto.setCollectionPointType(type);
        dto.setCollectionPointId(id);
        dto.setEmissionCategory(category);
        dto.setEmissionSubcategory(subcategory);
        return dto;
    }

    private MeterInfo meter(long id, String subcategory) {
        MeterInfo meter = new MeterInfo();
        meter.setId(id);
        meter.setName("测试电表");
        meter.setEmissionSubcategory(subcategory);
        return meter;
    }

    private EmissionNodeConfig completeOverride(long nodeId, String value, long factorId, int e1) {
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setNodeId(nodeId);
        config.setCarbonEmissionFactor(new BigDecimal(value));
        config.setCarbonEmissionFactorUnit("kgCO₂/kWh");
        config.setCarbonEmissionFactorDescription("原冻结快照");
        config.setCarbonEmissionFactorSource("ELECTRICITY");
        config.setCarbonEmissionFactorId(factorId);
        config.setCarbonEmissionFactorName("原正式因子");
        config.setCarbonEmissionFactorDqiE1Score(e1);
        config.setCarbonEmissionFactorDqiE2Score(5);
        config.setCarbonEmissionFactorDqiE3Score(5);
        config.setCarbonEmissionFactorDataYear(2025);
        config.setCarbonEmissionFactorDqiE5Score(5);
        config.setCarbonEmissionFactorDqiE6Score(5);
        return config;
    }
}
