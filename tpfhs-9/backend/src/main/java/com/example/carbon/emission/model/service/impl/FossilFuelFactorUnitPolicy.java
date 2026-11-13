package com.example.carbon.emission.model.service.impl;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.Set;

/**
 * 化石燃料因子的计量单位与因子单位规则。
 */
final class FossilFuelFactorUnitPolicy {

    private static final Set<String> SOLID_FUELS = Set.of(
            "FF_B", "FF_LB", "FF_CK", "FF_PC", "烟煤", "褐煤", "焦炭", "石油焦");
    private static final Set<String> LIQUID_FUELS = Set.of(
            "FF_G", "FF_D", "FF_C", "FF_F", "FF_LNG", "FF_LPG",
            "汽油", "柴油", "原油", "燃料油", "液化天然气", "液化石油气");
    private static final Set<String> GAS_FUELS = Set.of(
            "FF_NG", "FF_BFG", "FF_COG", "FF_COK", "天然气", "高炉煤气", "转炉煤气", "焦炉煤气");

    private static final Set<String> MASS_UNITS = Set.of("t", "kg", "g");
    private static final Set<String> LIQUID_UNITS = Set.of("t", "kg", "g", "L");
    private static final Set<String> GAS_UNITS = Set.of("m3", "wan_m3", "Nm3", "wan_Nm3");

    private static final Map<String, String> LEGACY_UNITS = Map.ofEntries(
            Map.entry("吨(t)", "t"), Map.entry("吨", "t"),
            Map.entry("千克(kg)", "kg"), Map.entry("千克", "kg"),
            Map.entry("克(g)", "g"), Map.entry("克", "g"),
            Map.entry("升(L)", "L"), Map.entry("升", "L"),
            Map.entry("立方米(m³)", "m3"), Map.entry("立方米", "m3"),
            Map.entry("万立方米(万m³)", "wan_m3"), Map.entry("万m³", "wan_m3"),
            Map.entry("标准立方米(Nm³)", "Nm3"), Map.entry("Nm³", "Nm3"),
            Map.entry("标准万立方米(万Nm³)", "wan_Nm3"), Map.entry("万Nm³", "wan_Nm3"),
            Map.entry("104 Nm3", "wan_Nm3")
    );

    private static final Map<String, String> FACTOR_UNITS = Map.ofEntries(
            Map.entry("t", "tCO₂/t"), Map.entry("kg", "tCO₂/kg"),
            Map.entry("g", "tCO₂/g"), Map.entry("L", "tCO₂/L"),
            Map.entry("m3", "tCO₂/m³"), Map.entry("wan_m3", "tCO₂/万m³"),
            Map.entry("Nm3", "tCO₂/Nm³"), Map.entry("wan_Nm3", "tCO₂/万Nm³")
    );

    private FossilFuelFactorUnitPolicy() {
    }

    static UnitRule normalizeAndValidate(String fuelType, String rawUnit) {
        String fuel = fuelType == null ? "" : fuelType.trim();
        String unit = normalizeUnit(rawUnit);
        Set<String> allowed;
        if (SOLID_FUELS.contains(fuel)) {
            allowed = MASS_UNITS;
        } else if (LIQUID_FUELS.contains(fuel)) {
            allowed = LIQUID_UNITS;
        } else if (GAS_FUELS.contains(fuel)) {
            allowed = GAS_UNITS;
        } else {
            throw badRequest("不支持的化石燃料品种: " + fuelType);
        }
        if (!allowed.contains(unit)) {
            throw badRequest("燃料品种“" + fuel + "”不支持计量单位“" + rawUnit + "”");
        }
        return new UnitRule(unit, FACTOR_UNITS.get(unit));
    }

    static String normalizeUnit(String rawUnit) {
        if (rawUnit == null || rawUnit.isBlank()) {
            throw badRequest("计量单位不能为空");
        }
        String unit = rawUnit.trim();
        if (FACTOR_UNITS.containsKey(unit)) {
            return unit;
        }
        String normalized = LEGACY_UNITS.get(unit);
        if (normalized == null) {
            throw badRequest("不支持的化石燃料计量单位: " + rawUnit);
        }
        return normalized;
    }

    private static ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    record UnitRule(String unitCode, String factorUnit) {
    }
}
