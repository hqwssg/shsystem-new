package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.DataDict;
import com.example.carbon.emission.model.entity.DataDictItem;
import com.example.carbon.emission.model.entity.FactorUnit;
import com.example.carbon.emission.model.entity.GhgUnit;
import com.example.carbon.emission.model.repository.DataDictItemRepository;
import com.example.carbon.emission.model.repository.DataDictRepository;
import com.example.carbon.emission.model.repository.FactorUnitRepository;
import com.example.carbon.emission.model.repository.GhgUnitRepository;
import com.example.carbon.emission.model.service.UnitConversionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/** 排放因子量纲计算的产品侧回归测试。 */
@ExtendWith(MockitoExtension.class)
class FactorDimensionServiceTest {

    @Mock private FactorUnitRepository factorUnitRepository;
    @Mock private GhgUnitRepository ghgUnitRepository;
    @Mock private DataDictRepository dataDictRepository;
    @Mock private DataDictItemRepository dataDictItemRepository;
    @Mock private UnitConversionService unitConversionService;
    @InjectMocks private FactorDimensionService service;

    private final DataDict dict = new DataDict();
    private final DataDictItem pePf = new DataDictItem();

    @BeforeEach
    void setUp() {
        dict.setId(1L);
        pePf.setItemCode("PE_PF");
        pePf.setItemValue("外购电力");
    }

    @Test
    void calculatesMwhFactorWithoutRescalingCarbon() {
        stubSubcategory("外购电力");
        stubFactorUnit("tCO₂/MWh", "tCO2", "MWh", "PE_PF");
        stubGhg("tCO2", "CO2", "t");
        when(unitConversionService.convertRequired("PE_PF", "MWh", "MWh", new BigDecimal("40")))
                .thenReturn(new BigDecimal("40"));

        FactorDimensionService.CarbonResult result = service.calculate(
                "外购电力", new BigDecimal("40"), "MWh",
                new BigDecimal("0.5"), "tCO2/MWh");

        assertThat(result.activityInFactorUnit()).isEqualByComparingTo("40");
        assertThat(result.carbonTco2e()).isEqualByComparingTo("20");
        assertThat(result.normalizedFactorUnit()).isEqualTo("tCO₂/MWh");
    }

    @Test
    void convertsKwhToFactorDenominatorBeforeMultiplication() {
        stubSubcategory("PE_PF");
        stubFactorUnit("tCO₂/MWh", "tCO2", "MWh", "PE_PF");
        stubGhg("tCO2", "CO2", "t");
        when(unitConversionService.convertRequired("PE_PF", "kWh", "MWh", new BigDecimal("40000")))
                .thenReturn(new BigDecimal("40"));

        FactorDimensionService.CarbonResult result = service.calculate(
                "PE_PF", new BigDecimal("40000"), "kWh",
                new BigDecimal("0.5"), "tCO₂/MWh");

        assertThat(result.carbonTco2e()).isEqualByComparingTo("20");
    }

    @Test
    void convertsKgCo2NumeratorToTonnesCo2e() {
        stubSubcategory("PE_PF");
        stubFactorUnit("kgCO₂/kWh", "kgCO2", "kWh", "PE_PF");
        stubGhg("kgCO2", "CO2", "kg");
        when(unitConversionService.convertRequired("PE_PF", "kWh", "kWh", new BigDecimal("40000")))
                .thenReturn(new BigDecimal("40000"));

        FactorDimensionService.CarbonResult result = service.calculate(
                "PE_PF", new BigDecimal("40000"), "kWh",
                new BigDecimal("0.5306"), "kgCO₂/kWh");

        assertThat(result.carbonTco2e()).isEqualByComparingTo("21.224");
    }

    @Test
    void calculatesPurchasedHeatUsingTheSelectedTonneFactorUnit() {
        when(dataDictRepository.findByDictCode("emission_subcategory")).thenReturn(Optional.of(dict));
        stubFactorUnit("tCO₂/GJ", "tCO2", "GJ", "PH_HD");
        stubGhg("tCO2", "CO2", "t");
        when(unitConversionService.convertRequired(
                "PH_HD", "GJ", "GJ", new BigDecimal("18929.46")))
                .thenReturn(new BigDecimal("18929.46"));

        FactorDimensionService.CarbonResult result = service.calculate(
                "heat", new BigDecimal("18929.46"), "GJ",
                new BigDecimal("0.11"), "tCO₂/GJ");

        assertThat(result.carbonTco2e()).isEqualByComparingTo("2082.2406");
        assertThat(result.normalizedFactorUnit()).isEqualTo("tCO₂/GJ");
    }

    @Test
    void rejectsNonCo2NumeratorUntilGwpIsConfigured() {
        stubSubcategory("PE_PF");
        stubFactorUnit("kgCH₄/kWh", "kgCH4", "kWh", "PE_PF");
        stubGhg("kgCH4", "CH4", "kg");
        when(unitConversionService.convertRequired(eq("PE_PF"), eq("kWh"), eq("kWh"), any()))
                .thenAnswer(invocation -> invocation.getArgument(3));

        assertThatThrownBy(() -> service.calculate(
                "PE_PF", BigDecimal.ONE, "kWh", BigDecimal.ONE, "kgCH₄/kWh"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("GWP");
    }

    @Test
    void rejectsMissingFactorUnit() {
        stubSubcategory("PE_PF");
        assertThatThrownBy(() -> service.calculate(
                "PE_PF", BigDecimal.ONE, "kWh", BigDecimal.ONE, null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("缺少单位");
    }

    @Test
    void resolvesCollectionSourceAlias() {
        when(dataDictRepository.findByDictCode("emission_subcategory")).thenReturn(Optional.of(dict));
        assertThat(service.resolveSubcategoryCode("purchased-electricity")).isEqualTo("PE_PF");
        assertThat(service.resolveSubcategoryCode("diesel")).isEqualTo("FF_D");
    }

    @Test
    void keepsDictionaryCodeAndDisplayValueResolution() {
        when(dataDictRepository.findByDictCode("emission_subcategory")).thenReturn(Optional.of(dict));
        when(dataDictItemRepository.findByDictIdAndItemCode(1L, "PE_PF")).thenReturn(Optional.of(pePf));
        assertThat(service.resolveSubcategoryCode("PE_PF")).isEqualTo("PE_PF");

        when(dataDictItemRepository.findByDictIdAndItemCode(1L, "外购电力")).thenReturn(Optional.empty());
        when(dataDictItemRepository.findByDictIdAndItemValue(1L, "外购电力")).thenReturn(Optional.of(pePf));
        assertThat(service.resolveSubcategoryCode("外购电力")).isEqualTo("PE_PF");
    }

    @Test
    void rejectsUnknownValue() {
        when(dataDictRepository.findByDictCode("emission_subcategory")).thenReturn(Optional.of(dict));
        when(dataDictItemRepository.findByDictIdAndItemCode(anyLong(), anyString())).thenReturn(Optional.empty());
        when(dataDictItemRepository.findByDictIdAndItemValue(anyLong(), anyString())).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.resolveSubcategoryCode("unknown-source"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("无法解析排放数据小类");
    }
    private void stubSubcategory(String input) {
        when(dataDictRepository.findByDictCode("emission_subcategory")).thenReturn(Optional.of(dict));
        if ("PE_PF".equals(input)) {
            when(dataDictItemRepository.findByDictIdAndItemCode(1L, "PE_PF"))
                    .thenReturn(Optional.of(pePf));
        } else {
            when(dataDictItemRepository.findByDictIdAndItemCode(1L, input)).thenReturn(Optional.empty());
            when(dataDictItemRepository.findByDictIdAndItemValue(1L, input)).thenReturn(Optional.of(pePf));
        }
    }

    private void stubFactorUnit(String name, String numerator, String denominator, String subcategory) {
        FactorUnit unit = new FactorUnit();
        unit.setFactorUnitCode(name.replace("/", "_per_"));
        unit.setFactorUnitName(name);
        unit.setNumeratorGhgCode(numerator);
        unit.setDenominatorUnitCode(denominator);
        unit.setSubcategoryCode(subcategory);
        unit.setStatus(1);
        when(factorUnitRepository.findAllByStatus(1)).thenReturn(List.of(unit));
    }

    private void stubGhg(String code, String type, String massUnit) {
        GhgUnit unit = new GhgUnit();
        unit.setGhgCode(code);
        unit.setGhgType(type);
        unit.setMassUnitCode(massUnit);
        unit.setStatus(1);
        when(ghgUnitRepository.findByGhgCode(code)).thenReturn(Optional.of(unit));
    }
}
