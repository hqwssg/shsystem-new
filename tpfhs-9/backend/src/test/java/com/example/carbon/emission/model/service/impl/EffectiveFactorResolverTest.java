package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.DefaultFactor;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.repository.DefaultFactorRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EffectiveFactorResolverTest {

    @Mock DefaultFactorRepository repository;
    @Mock FactorDimensionService dimensions;

    @Test
    void completeNodeSnapshotWinsWithoutReadingTemplate() {
        EmissionNodeConfig config = config("0.8", "tCO₂/MWh");
        config.setCarbonEmissionFactorSource("ELECTRICITY");
        config.setCarbonEmissionFactorId(12L);
        config.setCarbonEmissionFactorName("冻结的正式因子");
        config.setCarbonEmissionFactorDataYear(2025);
        config.setCarbonEmissionFactorDqiE1Score(5);
        config.setCarbonEmissionFactorDqiE2Score(4);
        config.setCarbonEmissionFactorDqiE3Score(3);
        config.setCarbonEmissionFactorDqiE5Score(5);
        config.setCarbonEmissionFactorDqiE6Score(4);
        EffectiveFactorResolver.FactorSnapshot result = resolver().resolve(config, 9L, "PE_PF");

        assertThat(result.value()).isEqualByComparingTo("0.8");
        assertThat(result.unit()).isEqualTo("tCO₂/MWh");
        assertThat(result.source()).isEqualTo(EffectiveFactorResolver.SOURCE_NODE_OVERRIDE);
        assertThat(result.factorId()).isEqualTo(12L);
        assertThat(result.factorName()).isEqualTo("冻结的正式因子");
        assertThat(result.dqi()).isEqualTo(new EffectiveFactorResolver.FactorDqiSnapshot(
                5, 4, 3, null, 2025, 5, 4));
        verify(repository, never()).findByTemplateIdAndSubcategoryCode(9L, "PE_PF");
    }

    @Test
    void incompleteNodeSnapshotIsRejectedInsteadOfMixingTemplateFields() {
        EmissionNodeConfig config = config(null, "kgCO₂/GJ");

        assertThatThrownBy(() -> resolver().resolve(config, 9L, "PH_HD"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("必须同时设置或同时为空");
    }

    @Test
    void emptyNodeSnapshotUsesOneCompleteTemplateSnapshot() {
        EmissionNodeConfig config = config(null, null);
        DefaultFactor factor = new DefaultFactor();
        factor.setStatus(1);
        factor.setFactorValue(new BigDecimal("0.11"));
        factor.setFactorUnit("tCO₂/GJ");
        factor.setFactorDescription("热力模板因子");
        when(dimensions.resolveSubcategoryCode("PH_HD")).thenReturn("PH_HD");
        when(repository.findByTemplateIdAndSubcategoryCode(9L, "PH_HD"))
                .thenReturn(Optional.of(factor));

        EffectiveFactorResolver.FactorSnapshot result = resolver().resolve(config, 9L, "PH_HD");

        assertThat(result.value()).isEqualByComparingTo("0.11");
        assertThat(result.unit()).isEqualTo("tCO₂/GJ");
        assertThat(result.source()).isEqualTo(EffectiveFactorResolver.SOURCE_TEMPLATE_DEFAULT);
    }

    @Test
    void missingTemplateDoesNotUseGlobalFallback() {
        assertThatThrownBy(() -> resolver().resolve(config(null, null), null, "PE_PF"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("未关联碳排放因子模板");
    }

    private EffectiveFactorResolver resolver() {
        return new EffectiveFactorResolver(repository, dimensions);
    }

    private EmissionNodeConfig config(String value, String unit) {
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setCarbonEmissionFactor(value == null ? null : new BigDecimal(value));
        config.setCarbonEmissionFactorUnit(unit);
        return config;
    }
}
