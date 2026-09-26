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
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.MathContext;
import java.util.Locale;

/**
 * 排放因子量纲解析与计算服务。
 * <p>
 * 因子单位同时定义了温室气体质量分子和活动量分母。本服务保证活动量先换算到
 * 因子分母单位，再将计算结果统一为 tCO2e，避免在汇总阶段用活动量换算系数
 * 二次缩放已经完成的碳排放量。
 */
@Service
public class FactorDimensionService {

    public static final String CARBON_RESULT_UNIT = "tCO2e";
    private static final MathContext MC = MathContext.DECIMAL64;

    @Autowired
    private FactorUnitRepository factorUnitRepository;

    @Autowired
    private GhgUnitRepository ghgUnitRepository;

    @Autowired
    private DataDictRepository dataDictRepository;

    @Autowired
    private DataDictItemRepository dataDictItemRepository;

    @Autowired
    private UnitConversionService unitConversionService;

    /** 完整的因子量纲计算结果。 */
    public record CarbonResult(BigDecimal activityInFactorUnit,
                               BigDecimal carbonTco2e,
                               String normalizedFactorUnit,
                               String denominatorUnit) {
    }

    /** 将小类编码或展示名称严格解析为 emission_subcategory 字典编码。 */
    public String resolveSubcategoryCode(String rawSubcategory) {
        if (rawSubcategory == null || rawSubcategory.isBlank()) {
            throw new IllegalStateException("排放数据小类为空");
        }
        String value = rawSubcategory.trim();
        DataDict dict = dataDictRepository.findByDictCode("emission_subcategory")
                .orElseThrow(() -> new IllegalStateException("缺少 emission_subcategory 数据字典"));
        return dataDictItemRepository.findByDictIdAndItemCode(dict.getId(), value)
                .map(DataDictItem::getItemCode)
                .orElseGet(() -> dataDictItemRepository.findByDictIdAndItemValue(dict.getId(), value)
                        .map(DataDictItem::getItemCode)
                        .orElseThrow(() -> new IllegalStateException("无法解析排放数据小类：" + value)));
    }

    /** 解析并校验因子单位是否启用、是否适用于目标小类。 */
    public FactorUnit resolveFactorUnit(String rawFactorUnit, String subcategoryCode) {
        if (rawFactorUnit == null || rawFactorUnit.isBlank()) {
            throw new IllegalStateException("碳排放因子缺少单位");
        }
        String target = normalizeFactorUnit(rawFactorUnit);
        return factorUnitRepository.findAllByStatus(1).stream()
                .filter(unit -> unit.getSubcategoryCode() == null
                        || unit.getSubcategoryCode().equalsIgnoreCase(subcategoryCode))
                .filter(unit -> normalizeFactorUnit(unit.getFactorUnitName()).equals(target)
                        || normalizeFactorUnit(unit.getFactorUnitCode()).equals(target))
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("不支持的碳排放因子单位："
                        + rawFactorUnit + "（小类=" + subcategoryCode + "）"));
    }

    /**
     * 按因子量纲计算碳排放量。当前正式因子只支持CO2；CH4/N2O需要正式GWP配置后方可启用。
     */
    public CarbonResult calculate(String rawSubcategory, BigDecimal activityValue,
                                  String activityUnit, BigDecimal factorValue,
                                  String factorUnitText) {
        if (factorValue == null) {
            throw new IllegalStateException("碳排放因子值为空");
        }
        String subcategoryCode = resolveSubcategoryCode(rawSubcategory);
        FactorUnit factorUnit = resolveFactorUnit(factorUnitText, subcategoryCode);
        BigDecimal activity = activityValue == null ? BigDecimal.ZERO : activityValue;
        BigDecimal convertedActivity = unitConversionService.convertRequired(
                subcategoryCode, activityUnit, factorUnit.getDenominatorUnitCode(), activity);

        GhgUnit numerator = ghgUnitRepository.findByGhgCode(factorUnit.getNumeratorGhgCode())
                .filter(unit -> unit.getStatus() != null && unit.getStatus() == 1)
                .orElseThrow(() -> new IllegalStateException("因子分子单位不存在或未启用："
                        + factorUnit.getNumeratorGhgCode()));
        if (!"CO2".equalsIgnoreCase(numerator.getGhgType())) {
            throw new IllegalStateException("因子分子为" + numerator.getGhgType()
                    + "，系统尚未配置GWP，不能折算为tCO2e");
        }

        BigDecimal massToTonnes = switch (numerator.getMassUnitCode()) {
            case "t" -> BigDecimal.ONE;
            case "kg" -> new BigDecimal("0.001");
            case "g" -> new BigDecimal("0.000001");
            default -> throw new IllegalStateException("不支持的温室气体质量单位："
                    + numerator.getMassUnitCode());
        };
        BigDecimal carbon = convertedActivity.multiply(factorValue, MC).multiply(massToTonnes, MC);
        return new CarbonResult(convertedActivity, carbon,
                factorUnit.getFactorUnitName(), factorUnit.getDenominatorUnitCode());
    }

    /** 校验活动量单位到因子分母单位存在严格换算路径。 */
    public void validateConversion(String rawSubcategory, String activityUnit, String factorUnitText) {
        String subcategoryCode = resolveSubcategoryCode(rawSubcategory);
        FactorUnit factorUnit = resolveFactorUnit(factorUnitText, subcategoryCode);
        unitConversionService.convertRequired(subcategoryCode, activityUnit,
                factorUnit.getDenominatorUnitCode(), BigDecimal.ONE);
    }

    private String normalizeFactorUnit(String value) {
        return value.trim()
                .replace("₂", "2")
                .replace("₄", "4")
                .replace("₂O", "2O")
                .replace("³", "3")
                .replace("²", "2")
                .replace(" ", "")
                .toLowerCase(Locale.ROOT);
    }
}
