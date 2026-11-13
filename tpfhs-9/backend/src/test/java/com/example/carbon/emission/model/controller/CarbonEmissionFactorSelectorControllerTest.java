package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.dto.FossilFuelEmissionFactorDTO;
import com.example.carbon.emission.model.service.ElectricityCarbonEmissionFactorService;
import com.example.carbon.emission.model.service.FossilFuelEmissionFactorService;
import com.example.carbon.emission.model.service.SteamCalculatorService;
import com.example.carbon.emission.model.service.ThermalEmissionFactorService;
import com.example.carbon.emission.model.service.WasteIncinerationFactorService;
import com.example.carbon.emission.model.service.WastewaterTreatmentFactorService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

/** 因子选择器必须返回可参与计算的完整因子量纲。 */
@ExtendWith(MockitoExtension.class)
class CarbonEmissionFactorSelectorControllerTest {

    @Mock private ElectricityCarbonEmissionFactorService electricityFactorService;
    @Mock private FossilFuelEmissionFactorService fossilFuelFactorService;
    @Mock private ThermalEmissionFactorService thermalFactorService;
    @Mock private WastewaterTreatmentFactorService wastewaterFactorService;
    @Mock private WasteIncinerationFactorService wasteIncinerationFactorService;
    @Mock private SteamCalculatorService steamCalculatorService;
    @InjectMocks private CarbonEmissionFactorSelectorController controller;

    @Test
    void fossilFuelSelectorReturnsFactorUnitInsteadOfActivityUnit() {
        FossilFuelEmissionFactorDTO factor = new FossilFuelEmissionFactorDTO();
        factor.setId(3L);
        factor.setEmissionFactorName("天然气排放因子");
        factor.setFuelType("天然气");
        factor.setSource("缺省值");
        factor.setUnit("万Nm³");
        factor.setFactorUnit("tCO₂/万Nm³");
        factor.setEmissionFactor(new BigDecimal("21.621888"));
        factor.setDescription("产品基线");
        factor.setDqiE1Score(5);
        factor.setDqiE2Score(5);
        factor.setDqiE3Score(5);
        factor.setEfDataYear(2025);
        factor.setDqiE5Score(5);
        factor.setDqiE6Score(5);
        when(fossilFuelFactorService.findAllByFuelType("天然气"))
                .thenReturn(List.of(factor));

        List<CarbonEmissionFactorSelectorController.FactorSelectionDTO> body =
                controller.getFactors("化石燃料", "天然气").getBody();

        assertThat(body).hasSize(1);
        assertThat(body.get(0).getUnit()).isEqualTo("tCO₂/万Nm³");
        assertThat(body.get(0).getFactorSource()).isEqualTo("FOSSIL");
        assertThat(body.get(0).getDqiComplete()).isTrue();
    }
}
