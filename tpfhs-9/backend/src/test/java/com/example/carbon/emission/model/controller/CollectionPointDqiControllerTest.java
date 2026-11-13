package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.entity.FossilFuelMeterInfo;
import com.example.carbon.emission.model.entity.PurchasedHeatMeterInfo;
import com.example.carbon.emission.model.repository.FossilFuelMeterInfoRepository;
import com.example.carbon.emission.model.repository.PurchasedHeatMeterInfoRepository;
import com.example.carbon.emission.model.service.EnergyAttributionService;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class CollectionPointDqiControllerTest {

    @Test
    void fossilCreateAndUpdatePersistServerCalculatedDqi() {
        FossilFuelMeterInfoRepository repository = mock(FossilFuelMeterInfoRepository.class);
        FossilFuelCollectionController controller = new FossilFuelCollectionController();
        ReflectionTestUtils.setField(controller, "meterRepository", repository);
        ReflectionTestUtils.setField(controller, "energyAttributionService", mock(EnergyAttributionService.class));
        when(repository.findMaxSortOrderBySubScopeId(any())).thenReturn(null);
        when(repository.save(any(FossilFuelMeterInfo.class))).thenAnswer(invocation -> {
            FossilFuelMeterInfo meter = invocation.getArgument(0);
            ReflectionTestUtils.invokeMethod(meter, meter.getId() == null ? "onCreate" : "onUpdate");
            if (meter.getId() == null) meter.setId(101L);
            return meter;
        });

        FossilFuelMeterInfo created = fossil("online_meter", "calib_valid_internal", "allocated");
        created.setDqiA1Score(1);
        created.setDqiA2Score(1);
        created.setDqiA4Score(1);
        FossilFuelMeterInfo createResult = controller.createMeter(created).getBody();
        assertEquals(5, createResult.getDqiA1Score());
        assertEquals(4, createResult.getDqiA2Score());
        assertEquals(3, createResult.getDqiA4Score());

        when(repository.findById(101L)).thenReturn(Optional.of(createResult));
        FossilFuelMeterInfo changed = fossil("manual_ledger", "calib_overdue_verified", "analogized");
        ResponseEntity<?> response = controller.updateMeter(101L, changed);
        FossilFuelMeterInfo updated = (FossilFuelMeterInfo) response.getBody();
        assertEquals("manual_ledger", updated.getAdMeteringTier());
        assertEquals("calib_overdue_verified", updated.getAdMeterCalibration());
        assertEquals("analogized", updated.getAdGeoBasis());
        assertEquals(4, updated.getDqiA1Score());
        assertEquals(3, updated.getDqiA2Score());
        assertEquals(2, updated.getDqiA4Score());

        FossilFuelMeterInfo cleared = fossil(null, null, null);
        controller.updateMeter(101L, cleared);
        assertNull(updated.getDqiA1Score());
        assertNull(updated.getDqiA2Score());
        assertNull(updated.getDqiA4Score());
    }

    @Test
    void heatCreateAndUpdatePersistServerCalculatedDqi() {
        PurchasedHeatMeterInfoRepository repository = mock(PurchasedHeatMeterInfoRepository.class);
        PurchasedHeatCollectionController controller = new PurchasedHeatCollectionController();
        ReflectionTestUtils.setField(controller, "meterRepository", repository);
        ReflectionTestUtils.setField(controller, "energyAttributionService", mock(EnergyAttributionService.class));
        when(repository.findBySubScopeIdOrderBySortOrderAsc(any())).thenReturn(List.of());
        when(repository.save(any(PurchasedHeatMeterInfo.class))).thenAnswer(invocation -> {
            PurchasedHeatMeterInfo meter = invocation.getArgument(0);
            ReflectionTestUtils.invokeMethod(meter, meter.getId() == null ? "onCreate" : "onUpdate");
            if (meter.getId() == null) meter.setId(201L);
            return meter;
        });

        PurchasedHeatMeterInfo created = heat("online_meter", "calib_valid_cert", "direct_metered");
        created.setDqiA1Score(1);
        created.setDqiA2Score(1);
        created.setDqiA4Score(1);
        PurchasedHeatMeterInfo createResult = controller.createMeter(created).getBody();
        assertEquals(5, createResult.getDqiA1Score());
        assertEquals(5, createResult.getDqiA2Score());
        assertEquals(5, createResult.getDqiA4Score());

        when(repository.findById(201L)).thenReturn(Optional.of(createResult));
        PurchasedHeatMeterInfo changed = heat("statistical_report", "calib_status_unknown", "default_value");
        PurchasedHeatMeterInfo updated = (PurchasedHeatMeterInfo) controller.updateMeter(201L, changed).getBody();
        assertEquals("statistical_report", updated.getAdMeteringTier());
        assertEquals("calib_status_unknown", updated.getAdMeterCalibration());
        assertEquals("default_value", updated.getAdGeoBasis());
        assertEquals(3, updated.getDqiA1Score());
        assertEquals(1, updated.getDqiA2Score());
        assertEquals(1, updated.getDqiA4Score());
    }

    @Test
    void fossilAndHeatTreeNodesExposeRawBasisAndScores() {
        FossilFuelCollectionController fossilController = new FossilFuelCollectionController();
        FossilFuelMeterInfoRepository fossilRepository = mock(FossilFuelMeterInfoRepository.class);
        ReflectionTestUtils.setField(fossilController, "meterRepository", fossilRepository);
        ReflectionTestUtils.setField(fossilController, "energyAttributionService", mock(EnergyAttributionService.class));
        when(fossilRepository.findByParentMeterIdOrderBySortOrderAsc(any())).thenReturn(List.of());
        FossilFuelMeterInfo fossil = fossil("online_meter", "calib_valid_internal", "allocated");
        ReflectionTestUtils.invokeMethod(fossil, "onCreate");
        Map<String, Object> fossilNode = ReflectionTestUtils.invokeMethod(
                fossilController, "buildMeterNode", fossil, "天然气", 1L);
        assertDqi(fossilNode, "online_meter", "calib_valid_internal", "allocated", 5, 4, 3);

        PurchasedHeatCollectionController heatController = new PurchasedHeatCollectionController();
        PurchasedHeatMeterInfoRepository heatRepository = mock(PurchasedHeatMeterInfoRepository.class);
        ReflectionTestUtils.setField(heatController, "meterRepository", heatRepository);
        ReflectionTestUtils.setField(heatController, "energyAttributionService", mock(EnergyAttributionService.class));
        when(heatRepository.findByParentMeterIdOrderBySortOrderAsc(any())).thenReturn(List.of());
        PurchasedHeatMeterInfo heat = heat("manual_ledger", "calib_not_applicable", "ledger_complete");
        ReflectionTestUtils.invokeMethod(heat, "onCreate");
        Map<String, Object> heatNode = ReflectionTestUtils.invokeMethod(
                heatController, "buildMeterNode", heat, "蒸汽", 2L);
        assertDqi(heatNode, "manual_ledger", "calib_not_applicable", "ledger_complete", 4, 5, 4);
    }

    private static FossilFuelMeterInfo fossil(String a1, String a2, String a4) {
        FossilFuelMeterInfo meter = new FossilFuelMeterInfo();
        meter.setName("DQI fossil");
        meter.setSubScopeId(1L);
        meter.setAdMeteringTier(a1);
        meter.setAdMeterCalibration(a2);
        meter.setAdGeoBasis(a4);
        return meter;
    }

    private static PurchasedHeatMeterInfo heat(String a1, String a2, String a4) {
        PurchasedHeatMeterInfo meter = new PurchasedHeatMeterInfo();
        meter.setName("DQI heat");
        meter.setSubScopeId(2L);
        meter.setAdMeteringTier(a1);
        meter.setAdMeterCalibration(a2);
        meter.setAdGeoBasis(a4);
        return meter;
    }

    private static void assertDqi(Map<String, Object> node, String a1, String a2, String a4,
                                  int s1, int s2, int s4) {
        assertEquals(a1, node.get("adMeteringTier"));
        assertEquals(a2, node.get("adMeterCalibration"));
        assertEquals(a4, node.get("adGeoBasis"));
        assertEquals(s1, node.get("dqiA1Score"));
        assertEquals(s2, node.get("dqiA2Score"));
        assertEquals(s4, node.get("dqiA4Score"));
    }
}
