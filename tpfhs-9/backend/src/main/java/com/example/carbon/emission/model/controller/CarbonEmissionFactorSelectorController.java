package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.dto.*;
import com.example.carbon.emission.model.service.*;
import com.example.carbon.emission.model.support.DqiScoring;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/emission-factor-selector")
@CrossOrigin(origins = "*", allowCredentials = "false")
public class CarbonEmissionFactorSelectorController {

    private static final Logger logger = LoggerFactory.getLogger(CarbonEmissionFactorSelectorController.class);

    @Autowired
    private ElectricityCarbonEmissionFactorService electricityFactorService;

    @Autowired
    private FossilFuelEmissionFactorService fossilFuelFactorService;

    @Autowired
    private ThermalEmissionFactorService thermalFactorService;

    @Autowired
    private WastewaterTreatmentFactorService wastewaterFactorService;

    @Autowired
    private WasteIncinerationFactorService wasteIncinerationFactorService;

    @Autowired
    private SteamCalculatorService steamCalculatorService;

    @GetMapping("/factors")
    public ResponseEntity<List<FactorSelectionDTO>> getFactors(
            @RequestParam String category,
            @RequestParam(required = false) String subcategory) {
        
        List<FactorSelectionDTO> result = new ArrayList<>();
        
        if ("购入的电力".equals(category) || "输出的电力".equals(category)) {
            result = getElectricityFactors();
        } else if ("化石燃料".equals(category)) {
            result = getFossilFuelFactors(subcategory);
        } else if ("购入的热力".equals(category)) {
            result = getThermalFactors(subcategory);
        } else if ("废弃物处理".equals(category)) {
            result = getWasteFactors(subcategory);
        }
        
        return ResponseEntity.ok(result);
    }

    @PostMapping("/calculate-steam")
    public ResponseEntity<FactorResultDTO> calculateSteamFactor(
            @RequestBody SteamCalculationRequest request) {
        
        ThermalEmissionFactorDTO thermalFactor = thermalFactorService.findById(request.getFactorId());
        if (thermalFactor == null) {
            return ResponseEntity.badRequest().body(FactorResultDTO.error("未找到指定的热力排放因子"));
        }
        
        BigDecimal ef = thermalFactor.getEmissionFactor();
        
        if ("饱和蒸汽".equals(request.getSteamType())) {
            return calculateSaturatedSteam(request, ef);
        } else if ("过热蒸汽".equals(request.getSteamType())) {
            return calculateSuperheatedSteam(request, ef);
        }
        
        return ResponseEntity.badRequest().body(FactorResultDTO.error("未知的蒸汽类型"));
    }

    @PostMapping("/calculate-hot-water")
    public ResponseEntity<FactorResultDTO> calculateHotWaterFactor(
            @RequestBody HotWaterCalculationRequest request) {
        
        ThermalEmissionFactorDTO thermalFactor = thermalFactorService.findById(request.getFactorId());
        if (thermalFactor == null) {
            return ResponseEntity.badRequest().body(FactorResultDTO.error("未找到指定的热力排放因子"));
        }
        
        BigDecimal ef = thermalFactor.getEmissionFactor();
        BigDecimal temperature = request.getTemperature();
        
        BigDecimal result = temperature.subtract(BigDecimal.valueOf(20))
                .multiply(BigDecimal.valueOf(4.1868))
                .multiply(ef)
                .divide(BigDecimal.valueOf(1000), 6, RoundingMode.HALF_UP);
        
        String description = String.format("质量单位计量%s℃的热水，热力排放因子=%s", 
                temperature, ef);
        
        return ResponseEntity.ok(FactorResultDTO.success(result.toPlainString(), description));
    }

    private ResponseEntity<FactorResultDTO> calculateSaturatedSteam(
            SteamCalculationRequest request, BigDecimal ef) {

        BigDecimal temperature = request.getTemperature();

        // 调用Python脚本计算饱和蒸汽性质（压力和焓值）
        Map<String, Object> calcResult = steamCalculatorService.calculateSaturationProperties(temperature.doubleValue());

        if (!Boolean.TRUE.equals(calcResult.get("success"))) {
            String errorMsg = (String) calcResult.get("error");
            logger.error("Python计算饱和蒸汽性质失败: {}", errorMsg);
            return ResponseEntity.badRequest().body(FactorResultDTO.error("计算饱和蒸汽性质失败: " + errorMsg));
        }

        BigDecimal enthalpy = new BigDecimal(calcResult.get("enthalpy").toString());
        BigDecimal pressure = new BigDecimal(calcResult.get("pressure").toString());

        BigDecimal result = enthalpy.subtract(BigDecimal.valueOf(83.74))
                .multiply(ef)
                .divide(BigDecimal.valueOf(1000), 6, RoundingMode.HALF_UP);

        String description = String.format("饱和蒸汽，温度=%s℃，气压=%sMPa，饱和蒸汽焓值=%skJ/kg，热力排放因子=%s",
                temperature, pressure, enthalpy, ef);

        return ResponseEntity.ok(FactorResultDTO.success(result.toPlainString(), description));
    }

    private ResponseEntity<FactorResultDTO> calculateSuperheatedSteam(
            SteamCalculationRequest request, BigDecimal ef) {

        BigDecimal temperature = request.getTemperature();
        BigDecimal pressure = request.getPressure();

        // 调用Python脚本计算过热蒸汽焓值（脚本内部会进行条件验证）
        Map<String, Object> calcResult = steamCalculatorService.calculateSuperheatedProperties(temperature.doubleValue(), pressure.doubleValue());

        if (!Boolean.TRUE.equals(calcResult.get("success"))) {
            String errorMsg = (String) calcResult.get("error");
            logger.error("Python计算过热蒸汽性质失败: {}", errorMsg);
            return ResponseEntity.badRequest().body(FactorResultDTO.error(errorMsg));
        }

        BigDecimal enthalpy = new BigDecimal(calcResult.get("enthalpy").toString());

        BigDecimal result = enthalpy.subtract(BigDecimal.valueOf(83.74))
                .multiply(ef)
                .divide(BigDecimal.valueOf(1000), 6, RoundingMode.HALF_UP);

        String description = String.format("过热蒸汽，温度=%s℃，气压=%sMPa，过热蒸汽焓值=%skJ/kg，热力排放因子=%s",
                temperature, pressure, enthalpy, ef);

        return ResponseEntity.ok(FactorResultDTO.success(result.toPlainString(), description));
    }

    private List<FactorSelectionDTO> getElectricityFactors() {
        return electricityFactorService.findAll().stream()
                .map(dto -> FactorSelectionDTO.builder()
                        .id(dto.getId())
                        .factorSource("ELECTRICITY")
                        .dqiComplete(isDqiComplete(dto.getDqiE1Score(), dto.getDqiE2Score(), dto.getDqiE3Score(),
                                dto.getDqiE4Score(), dto.getEfDataYear(), dto.getDqiE5Score(), dto.getDqiE6Score()))
                        .name(dto.getFactorName())
                        .value(dto.getFactorValue().toPlainString())
                        .unit(dto.getUnit())
                        .description(dto.getFactorName() + "：" + dto.getDescription())
                        .build())
                .collect(Collectors.toList());
    }

    private List<FactorSelectionDTO> getFossilFuelFactors(String fuelType) {
        String lookup = normalizeFuelType(fuelType);
        List<com.example.carbon.emission.model.dto.FossilFuelEmissionFactorDTO> factors =
                fossilFuelFactorService.findAllByFuelType(lookup);
        // 兼容历史采集点保存的英文名称/小类编码；因子库统一使用中文燃料名称。
        if (factors.isEmpty() && fuelType != null && !lookup.equals(fuelType)) {
            factors = fossilFuelFactorService.findAllByFuelType(fuelType);
        }
        if (factors.isEmpty() && lookup != null && !lookup.isBlank()) {
            factors = fossilFuelFactorService.searchByFuelType(lookup);
        }
        return factors.stream()
                .map(dto -> FactorSelectionDTO.builder()
                        .id(dto.getId())
                        .factorSource("FOSSIL")
                        .dqiComplete(isDqiComplete(dto.getDqiE1Score(), dto.getDqiE2Score(), dto.getDqiE3Score(),
                                dto.getDqiE4Score(), dto.getEfDataYear(), dto.getDqiE5Score(), dto.getDqiE6Score()))
                        .name(dto.getEmissionFactorName())
                        .value(dto.getEmissionFactor().toPlainString())
                        // 选择器返回的是排放因子的完整量纲，而不是燃料采集单位。
                        // 对天然气而言二者分别为 tCO₂/万Nm³ 与 万Nm³；混用会使
                        // 前端把活动量单位保存成因子单位，模板校验也无法解析分子。
                        .unit(dto.getFactorUnit())
                        .description(String.format("%s：%s，%s，%s", 
                                dto.getEmissionFactorName(), 
                                dto.getFuelType(), 
                                dto.getSource(), 
                                dto.getDescription()))
                        .build())
                .collect(Collectors.toList());
    }

    private String normalizeFuelType(String fuelType) {
        if (fuelType == null) return "";
        return switch (fuelType.trim().toLowerCase(java.util.Locale.ROOT)) {
            case "ff_b", "bituminous-coal", "bituminous_coal", "coal" -> "烟煤";
            case "ff_lb", "lignite" -> "褐煤";
            case "ff_ck", "coke" -> "焦炭";
            case "ff_pc", "petroleum-coke", "petroleum_coke" -> "石油焦";
            case "ff_ng", "natural-gas", "natural_gas" -> "天然气";
            case "ff_lng", "lng" -> "液化天然气";
            case "ff_lpg", "lpg" -> "液化石油气";
            case "ff_g", "gasoline", "petrol" -> "汽油";
            case "ff_d", "diesel" -> "柴油";
            case "ff_c", "crude-oil", "crude_oil" -> "原油";
            case "ff_f", "fuel-oil", "fuel_oil" -> "燃料油";
            case "ff_bfg", "blast-furnace-gas", "blast_furnace_gas" -> "高炉煤气";
            case "ff_cog", "converter-gas", "converter_gas" -> "转炉煤气";
            case "ff_cok", "coke-oven-gas", "coke_oven_gas" -> "焦炉煤气";
            default -> fuelType.trim();
        };
    }

    private List<FactorSelectionDTO> getThermalFactors(String subcategory) {
        return thermalFactorService.findAll().stream()
                .map(dto -> FactorSelectionDTO.builder()
                        .id(dto.getId())
                        .factorSource("THERMAL")
                        .dqiComplete(isDqiComplete(dto.getDqiE1Score(), dto.getDqiE2Score(), dto.getDqiE3Score(),
                                dto.getDqiE4Score(), dto.getEfDataYear(), dto.getDqiE5Score(), dto.getDqiE6Score()))
                        .name(dto.getEmissionFactorName())
                        .value(dto.getEmissionFactor().toPlainString())
                        .unit(dto.getUnit())
                        .description(dto.getEmissionFactorName() + "：" + dto.getSource() + "，" + dto.getDescription())
                        .build())
                .collect(Collectors.toList());
    }

    private List<FactorSelectionDTO> getWasteFactors(String subcategory) {
        if ("废水处理排放".equals(subcategory)) {
            return wastewaterFactorService.findAll().stream()
                    .map(dto -> FactorSelectionDTO.builder()
                            .id(dto.getId())
                            .factorSource("WASTEWATER")
                            .dqiComplete(false)
                            .name(dto.getEmissionFactorName())
                            .value(dto.getEmissionFactor().toPlainString())
                            .unit(dto.getUnit())
                            .description(String.format("%s：%s，%s，需氧浓度系数（COD或BOD，单位：mg/L）=%s，最大甲烷产生能力(单位tCH4/t）=%s，甲烷修正因子=%s，甲烷的全球变暖潜能值=%s，%s",
                                    dto.getEmissionFactorName(),
                                    dto.getWastewaterType(),
                                    dto.getSource(),
                                    dto.getOd(),
                                    dto.getBo(),
                                    dto.getMcf(),
                                    dto.getGwp(),
                                    dto.getDescription()))
                            .build())
                    .collect(Collectors.toList());
        } else if ("固体废弃物处理排放".equals(subcategory)) {
            return wasteIncinerationFactorService.findAll().stream()
                    .map(dto -> FactorSelectionDTO.builder()
                            .id(dto.getId())
                            .factorSource("WASTE_INCINERATION")
                            .dqiComplete(isDqiComplete(dto.getDqiE1Score(), dto.getDqiE2Score(), dto.getDqiE3Score(),
                                    dto.getDqiE4Score(), dto.getEfDataYear(), dto.getDqiE5Score(), dto.getDqiE6Score()))
                            .name(dto.getEmissionFactorName())
                            .value(dto.getEmissionFactor().toPlainString())
                            .unit(dto.getUnit())
                            .description(String.format("%s：%s，%s，废弃物中的碳含量比例=%s，废弃物中的化石碳在总碳中的比例=%s，废弃物焚烧炉的完全燃烧效率=%s，%s",
                                    dto.getEmissionFactorName(),
                                    dto.getWasteType(),
                                    dto.getSource(),
                                    dto.getCcw(),
                                    dto.getFcf(),
                                    dto.getCe(),
                                    dto.getDescription()))
                            .build())
                    .collect(Collectors.toList());
        }
        return new ArrayList<>();
    }

    private boolean isDqiComplete(Integer e1, Integer e2, Integer e3, Integer e4,
                                  Integer factorYear, Integer e5, Integer e6) {
        return DqiScoring.isValidScore(e1) && DqiScoring.isValidScore(e2)
                && DqiScoring.isValidScore(e3) && DqiScoring.isValidScore(e5)
                && DqiScoring.isValidScore(e6)
                && (DqiScoring.isValidScore(e4) || factorYear != null);
    }

    public static class FactorSelectionDTO {
        private Long id;
        private String factorSource;
        private Boolean dqiComplete;
        private String name;
        private String value;
        private String unit;
        private String description;

        public static Builder builder() {
            return new Builder();
        }

        public static class Builder {
            private final FactorSelectionDTO dto = new FactorSelectionDTO();
            
            public Builder id(Long id) { dto.id = id; return this; }
            public Builder factorSource(String factorSource) { dto.factorSource = factorSource; return this; }
            public Builder dqiComplete(Boolean dqiComplete) { dto.dqiComplete = dqiComplete; return this; }
            public Builder name(String name) { dto.name = name; return this; }
            public Builder value(String value) { dto.value = value; return this; }
            public Builder unit(String unit) { dto.unit = unit; return this; }
            public Builder description(String description) { dto.description = description; return this; }
            
            public FactorSelectionDTO build() { return dto; }
        }

        public Long getId() { return id; }
        public void setId(Long id) { this.id = id; }
        public String getFactorSource() { return factorSource; }
        public void setFactorSource(String factorSource) { this.factorSource = factorSource; }
        public Boolean getDqiComplete() { return dqiComplete; }
        public void setDqiComplete(Boolean dqiComplete) { this.dqiComplete = dqiComplete; }
        public String getName() { return name; }
        public void setName(String name) { this.name = name; }
        public String getValue() { return value; }
        public void setValue(String value) { this.value = value; }
        public String getUnit() { return unit; }
        public void setUnit(String unit) { this.unit = unit; }
        public String getDescription() { return description; }
        public void setDescription(String description) { this.description = description; }
    }

    public static class FactorResultDTO {
        private boolean success;
        private String message;
        private String factorValue;
        private String description;

        public static FactorResultDTO success(String factorValue, String description) {
            FactorResultDTO dto = new FactorResultDTO();
            dto.success = true;
            dto.factorValue = factorValue;
            dto.description = description;
            return dto;
        }

        public static FactorResultDTO error(String message) {
            FactorResultDTO dto = new FactorResultDTO();
            dto.success = false;
            dto.message = message;
            return dto;
        }

        public boolean isSuccess() { return success; }
        public void setSuccess(boolean success) { this.success = success; }
        public String getMessage() { return message; }
        public void setMessage(String message) { this.message = message; }
        public String getFactorValue() { return factorValue; }
        public void setFactorValue(String factorValue) { this.factorValue = factorValue; }
        public String getDescription() { return description; }
        public void setDescription(String description) { this.description = description; }
    }

    public static class SteamCalculationRequest {
        private Long factorId;
        private String steamType;
        private BigDecimal temperature;
        private BigDecimal pressure;

        public Long getFactorId() { return factorId; }
        public void setFactorId(Long factorId) { this.factorId = factorId; }
        public String getSteamType() { return steamType; }
        public void setSteamType(String steamType) { this.steamType = steamType; }
        public BigDecimal getTemperature() { return temperature; }
        public void setTemperature(BigDecimal temperature) { this.temperature = temperature; }
        public BigDecimal getPressure() { return pressure; }
        public void setPressure(BigDecimal pressure) { this.pressure = pressure; }
    }

    public static class HotWaterCalculationRequest {
        private Long factorId;
        private BigDecimal temperature;

        public Long getFactorId() { return factorId; }
        public void setFactorId(Long factorId) { this.factorId = factorId; }
        public BigDecimal getTemperature() { return temperature; }
        public void setTemperature(BigDecimal temperature) { this.temperature = temperature; }
    }
}
