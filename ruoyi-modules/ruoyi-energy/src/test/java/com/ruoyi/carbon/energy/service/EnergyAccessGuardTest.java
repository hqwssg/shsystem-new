package com.ruoyi.carbon.energy.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import com.ruoyi.carbon.energy.service.impl.EnergyServiceImpl;
import com.ruoyi.common.core.exception.ServiceException;

class EnergyAccessGuardTest
{
    @Test
    void acceptsFiveRunTypes()
    {
        assertEquals("timetable_audit", EnergyAccessGuard.requireRunType("timetable_audit"));
        assertEquals("timetable_optimization", EnergyAccessGuard.requireRunType("timetable_optimization"));
        assertEquals("dispatch", EnergyAccessGuard.requireRunType("dispatch"));
        assertEquals("rolling_rescheduling", EnergyAccessGuard.requireRunType("rolling_rescheduling"));
        assertEquals("joint_parameter_robustness", EnergyAccessGuard.requireRunType("joint_parameter_robustness"));
    }

    @Test
    void rejectsUnknownRunType()
    {
        assertThrows(ServiceException.class, () -> EnergyAccessGuard.requireRunType("optimize"));
    }

    @Test
    void rejectsPathTraversal()
    {
        assertThrows(ServiceException.class, () -> EnergyAccessGuard.requireRelativePath("../secret.csv"));
        assertThrows(ServiceException.class, () -> EnergyAccessGuard.requireRelativePath("/abs.json"));
        EnergyAccessGuard.requireRelativePath("timetable.csv");
        EnergyAccessGuard.requireRelativePath("platform/timetable.csv");
        assertEquals("platform/timetable.csv", EnergyAccessGuard.relativePath("platform\\timetable.csv"));
    }

    @Test
    void rollingWithheldCannotDispatch()
    {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("events", List.of(Map.of("commitStatus", "withheld_infeasible")));
        EnergyServiceImpl.annotateRollingHold(body);
        assertFalse((Boolean) body.get("dispatchAllowed"));
        assertEquals("withheld_infeasible", body.get("holdReason"));
    }

    @Test
    void rollingCommittedCanDispatch()
    {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("events", List.of(Map.of("commitStatus", "committed_robust_feasible")));
        EnergyServiceImpl.annotateRollingHold(body);
        assertTrue((Boolean) body.get("dispatchAllowed"));
    }

    @Test
    void parsesStoredRunParameters()
    {
        Map<String, Object> fromText = EnergyServiceImpl.parseJsonMap("{\"population_size\":12,\"heavy_count\":3}");
        assertEquals(12, ((Number) fromText.get("population_size")).intValue());
        Map<String, Object> fromMap = EnergyServiceImpl.parseJsonMap(Map.of("energy_scenario", "storage_no_direct"));
        assertEquals("storage_no_direct", fromMap.get("energy_scenario"));
    }
}
