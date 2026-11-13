package com.ruoyi.carbon.energy.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.energy.cli.EnergyCliClient;
import com.ruoyi.carbon.energy.config.EnergyProperties;
import com.ruoyi.carbon.energy.mapper.EnergyMapper;
import com.ruoyi.carbon.energy.service.impl.EnergyServiceImpl;
import com.ruoyi.carbon.energy.controller.EnergyController;
import com.ruoyi.common.core.exception.ServiceException;
import com.ruoyi.common.security.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;

class StoragePlanningServiceTest
{
    private EnergyMapper mapper;
    private EnergyServiceImpl service;

    @BeforeEach
    void setup()
    {
        mapper = mock(EnergyMapper.class);
        service = new EnergyServiceImpl(mapper, mock(EnergyCliClient.class), new EnergyProperties(), Runnable::run);
        when(mapper.selectRun("run")).thenReturn(Map.of("projectCode", "project", "runType", "storage_planning", "status", "succeeded"));
        when(mapper.countDeptProject(17L, "project")).thenReturn(1);
        when(mapper.selectStoragePlanningDecision("run")).thenAnswer(invocation -> new LinkedHashMap<>(Map.of(
            "decision", "recommend_build", "selectedStoragePlanId", "selected", "decisionJson", "{\"declared_search_domain\":{\"complete_for_declared_domain\":true},\"data_statuses\":[\"synthetic\"]}")));
        when(mapper.selectStoragePlan("run", "selected")).thenReturn(Map.of("storagePlanId", "selected"));
        when(mapper.selectStoragePlans("run", 0, 20)).thenReturn(List.of(Map.of("storagePlanId", "selected")));
        when(mapper.countStoragePlans("run")).thenReturn(121L);
        when(mapper.selectNoBuildStoragePlanId("run")).thenReturn("baseline");
    }

    @Test
    void sixthTaskAccepted()
    {
        assertEquals("storage_planning", EnergyAccessGuard.requireRunType("storage_planning"));
    }

    @Test
    void selectedPlanPagedResultsAndCamelCaseDetails()
    {
        Map<String, Object> body = service.storagePlanning(17L, "run", null, 1, 20);
        assertEquals(121L, body.get("total"));
        assertEquals(20, body.get("pageSize"));
        Map<?, ?> decision = (Map<?, ?>) body.get("decision");
        Map<?, ?> details = (Map<?, ?>) decision.get("details");
        assertTrue(details.containsKey("declaredSearchDomain"));
        assertEquals(Boolean.TRUE, ((Map<?, ?>) details.get("declaredSearchDomain")).get("completeForDeclaredDomain"));
        verify(mapper).selectStoragePlanDevices("selected");
        verify(mapper).selectStoragePlanScenarios("baseline");
    }

    @Test
    void departmentMustBeBound()
    {
        when(mapper.countDeptProject(17L, "project")).thenReturn(0);
        assertThrows(ServiceException.class, () -> service.storagePlanning(17L, "run", null, 1, 20));
        verify(mapper, never()).selectStoragePlanningDecision(anyString());
    }

    @Test
    void unsuccessfulTaskCannotReadResults()
    {
        when(mapper.selectRun("run")).thenReturn(Map.of("projectCode", "project", "runType", "storage_planning", "status", "failed"));
        assertThrows(ServiceException.class, () -> service.storagePlanning(17L, "run", null, 1, 20));
        verify(mapper, never()).selectStoragePlanningDecision(anyString());
    }

    @Test
    void foreignPlanCannotReadDevices()
    {
        assertThrows(ServiceException.class, () -> service.storagePlanning(17L, "run", "foreign-plan", 1, 20));
        verify(mapper, never()).selectStoragePlanDevices(anyString());
    }

    @Test
    void limitsAndOverflowRejected()
    {
        for (int[] page : new int[][] {{0,20},{1,0},{1,101},{Integer.MAX_VALUE,100}})
        {
            assertThrows(ServiceException.class, () -> service.storagePlanning(17L, "run", null, page[0], page[1]));
        }
        verify(mapper, never()).selectStoragePlans(anyString(), anyInt(), anyInt());
    }

    @Test
    void infeasibleBaselineOnlyReference()
    {
        when(mapper.selectStoragePlanningDecision("run")).thenReturn(new LinkedHashMap<>(Map.of("decision", "no_feasible_plan", "selectedStoragePlanId", "selected", "decisionJson", "{}")));
        assertEquals(Boolean.TRUE, service.storagePlanning(17L, "run", null, 1, 20).get("referenceOnly"));
    }

    @Test
    void controllerRouteRequiresExistingQueryPermission() throws Exception
    {
        var method = EnergyController.class.getMethod("storagePlanning", String.class, String.class, int.class, int.class);
        assertArrayEquals(new String[] {"/runs/{runId}/storage-planning"}, method.getAnnotation(GetMapping.class).value());
        assertArrayEquals(new String[] {"carbon:energy:query"}, method.getAnnotation(RequiresPermissions.class).value());
    }
}
