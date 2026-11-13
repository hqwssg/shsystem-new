package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.DefaultFactor;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.ElectricityCarbonEmissionFactor;
import com.example.carbon.emission.model.entity.FossilFuelEmissionFactor;
import com.example.carbon.emission.model.entity.ThermalEmissionFactor;
import com.example.carbon.emission.model.entity.WasteIncinerationFactor;
import com.example.carbon.emission.model.repository.DefaultFactorRepository;
import com.example.carbon.emission.model.repository.ElectricityCarbonEmissionFactorRepository;
import com.example.carbon.emission.model.repository.FossilFuelEmissionFactorRepository;
import com.example.carbon.emission.model.repository.ThermalEmissionFactorRepository;
import com.example.carbon.emission.model.repository.WasteIncinerationFactorRepository;
import com.example.carbon.emission.model.support.DqiScoring;
import com.example.carbon.emission.model.support.EmissionFactorDqi;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;

/**
 * Resolves the complete emission-factor snapshot used by validation, preview and calculation.
 * A value and unit always come from the same source; field-by-field fallback is forbidden.
 */
@Service
public class EffectiveFactorResolver {

    public static final String SOURCE_NODE_OVERRIDE = "NODE_OVERRIDE";
    public static final String SOURCE_TEMPLATE_DEFAULT = "TEMPLATE_DEFAULT";

    private final DefaultFactorRepository defaultFactorRepository;
    private final FactorDimensionService factorDimensionService;

    @Autowired(required = false)
    private ElectricityCarbonEmissionFactorRepository electricityFactorRepository;
    @Autowired(required = false)
    private FossilFuelEmissionFactorRepository fossilFuelFactorRepository;
    @Autowired(required = false)
    private ThermalEmissionFactorRepository thermalFactorRepository;
    @Autowired(required = false)
    private WasteIncinerationFactorRepository wasteFactorRepository;

    public EffectiveFactorResolver(DefaultFactorRepository defaultFactorRepository,
                                   FactorDimensionService factorDimensionService) {
        this.defaultFactorRepository = defaultFactorRepository;
        this.factorDimensionService = factorDimensionService;
    }

    public FactorSnapshot resolve(EmissionNodeConfig config, Long factorTemplateId, String subcategory) {
        BigDecimal nodeValue = config == null ? null : config.getCarbonEmissionFactor();
        String nodeUnit = trimToNull(config == null ? null : config.getCarbonEmissionFactorUnit());
        if ((nodeValue == null) != (nodeUnit == null)) {
            throw new IllegalStateException("采集节点因子覆盖不完整，因子值和单位必须同时设置或同时为空");
        }
        if (nodeValue != null) {
            return new FactorSnapshot(nodeValue, nodeUnit,
                    trimToNull(config.getCarbonEmissionFactorDescription()), SOURCE_NODE_OVERRIDE,
                    config.getCarbonEmissionFactorId(), config.getCarbonEmissionFactorName(),
                    nodeDqi(config));
        }

        if (factorTemplateId == null) {
            throw new IllegalStateException("核算模板未关联碳排放因子模板，且采集节点未设置完整覆盖因子");
        }
        String lookup = trimToNull(subcategory);
        if (lookup == null) {
            throw new IllegalStateException("采集节点缺少排放小类，无法匹配因子模板");
        }
        String canonical = lookup;
        try {
            canonical = factorDimensionService.resolveSubcategoryCode(lookup);
        } catch (IllegalStateException ignored) {
            // Custom names remain eligible for exact template-name matching.
        }

        DefaultFactor factor = defaultFactorRepository
                .findByTemplateIdAndSubcategoryCode(factorTemplateId, canonical)
                .orElseGet(() -> defaultFactorRepository
                        .findByTemplateIdAndSubcategoryName(factorTemplateId, lookup)
                        .orElse(null));
        if (factor == null || factor.getStatus() == null || factor.getStatus() != 1) {
            throw new IllegalStateException("因子模板未配置启用的排放小类因子：" + lookup);
        }
        String templateUnit = trimToNull(factor.getFactorUnit());
        if (factor.getFactorValue() == null || templateUnit == null) {
            throw new IllegalStateException("因子模板中的排放因子快照不完整：" + lookup);
        }
        return new FactorSnapshot(factor.getFactorValue(), templateUnit,
                trimToNull(factor.getFactorDescription()), SOURCE_TEMPLATE_DEFAULT,
                factor.getFactorId(), factor.getFactorName(), resolveDqi(factor));
    }

    private FactorDqiSnapshot resolveDqi(DefaultFactor factor) {
        if (factor.getFactorId() == null || factor.getFactorSource() == null) {
            return null;
        }
        EmissionFactorDqi source = switch (factor.getFactorSource()) {
            case "ELECTRICITY" -> electricityFactorRepository == null ? null
                    : electricityFactorRepository.findById(factor.getFactorId()).orElse(null);
            case "FOSSIL" -> fossilFuelFactorRepository == null ? null
                    : fossilFuelFactorRepository.findById(factor.getFactorId()).orElse(null);
            case "THERMAL" -> thermalFactorRepository == null ? null
                    : thermalFactorRepository.findById(factor.getFactorId()).orElse(null);
            case "WASTE_INCINERATION" -> wasteFactorRepository == null ? null
                    : wasteFactorRepository.findById(factor.getFactorId()).orElse(null);
            default -> null;
        };
        return source == null ? null : FactorDqiSnapshot.from(source);
    }

    /** Resolve the immutable provenance fields to freeze when a formal factor is selected. */
    public FactorReference resolveReference(String factorSource, Long factorId) {
        String source = trimToNull(factorSource);
        if (source == null || factorId == null) {
            throw new IllegalArgumentException("节点覆盖因子必须关联正式因子来源和主键");
        }
        return switch (source) {
            case "ELECTRICITY" -> {
                ElectricityCarbonEmissionFactor factor = electricityFactorRepository == null ? null
                        : electricityFactorRepository.findById(factorId).orElse(null);
                yield reference(source, factorId, factor == null ? null : factor.getFactorName(), factor);
            }
            case "FOSSIL" -> {
                FossilFuelEmissionFactor factor = fossilFuelFactorRepository == null ? null
                        : fossilFuelFactorRepository.findById(factorId).orElse(null);
                yield reference(source, factorId, factor == null ? null : factor.getEmissionFactorName(), factor);
            }
            case "THERMAL" -> {
                ThermalEmissionFactor factor = thermalFactorRepository == null ? null
                        : thermalFactorRepository.findById(factorId).orElse(null);
                yield reference(source, factorId, factor == null ? null : factor.getEmissionFactorName(), factor);
            }
            case "WASTE_INCINERATION" -> {
                WasteIncinerationFactor factor = wasteFactorRepository == null ? null
                        : wasteFactorRepository.findById(factorId).orElse(null);
                yield reference(source, factorId, factor == null ? null : factor.getEmissionFactorName(), factor);
            }
            default -> throw new IllegalArgumentException("不支持的正式因子来源：" + source);
        };
    }

    private FactorReference reference(String source, Long id, String name, EmissionFactorDqi factor) {
        if (factor == null) {
            throw new IllegalArgumentException("所选正式排放因子不存在或已删除");
        }
        FactorDqiSnapshot dqi = FactorDqiSnapshot.from(factor);
        if (!dqi.isComplete()) {
            throw new IllegalArgumentException("所选正式排放因子DQI不完整，请先完善因子质量信息");
        }
        return new FactorReference(source, id, name, dqi);
    }

    private FactorDqiSnapshot nodeDqi(EmissionNodeConfig config) {
        if (config.getCarbonEmissionFactorSource() == null || config.getCarbonEmissionFactorId() == null) {
            return null;
        }
        return new FactorDqiSnapshot(config.getCarbonEmissionFactorDqiE1Score(),
                config.getCarbonEmissionFactorDqiE2Score(),
                config.getCarbonEmissionFactorDqiE3Score(),
                config.getCarbonEmissionFactorDqiE4Score(),
                config.getCarbonEmissionFactorDataYear(),
                config.getCarbonEmissionFactorDqiE5Score(),
                config.getCarbonEmissionFactorDqiE6Score());
    }

    private String trimToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    public record FactorSnapshot(BigDecimal value, String unit, String description, String source,
                                 Long factorId, String factorName, FactorDqiSnapshot dqi) {
        public FactorSnapshot(BigDecimal value, String unit, String description, String source) {
            this(value, unit, description, source, null, null, null);
        }

        public FactorSnapshot(BigDecimal value, String unit, String description, String source,
                              FactorDqiSnapshot dqi) {
            this(value, unit, description, source, null, null, dqi);
        }
    }

    public record FactorReference(String source, Long factorId, String factorName, FactorDqiSnapshot dqi) {
    }

    public record FactorDqiSnapshot(Integer e1, Integer e2, Integer e3, Integer fixedE4,
                                    Integer factorYear, Integer e5, Integer e6) {
        static FactorDqiSnapshot from(EmissionFactorDqi source) {
            return new FactorDqiSnapshot(source.getDqiE1Score(), source.getDqiE2Score(),
                    source.getDqiE3Score(), source.getDqiE4Score(), source.getEfDataYear(),
                    source.getDqiE5Score(), source.getDqiE6Score());
        }

        public boolean isComplete() {
            return DqiScoring.isValidScore(e1) && DqiScoring.isValidScore(e2)
                    && DqiScoring.isValidScore(e3) && DqiScoring.isValidScore(e5)
                    && DqiScoring.isValidScore(e6)
                    && (DqiScoring.isValidScore(fixedE4) || factorYear != null);
        }
    }
}
