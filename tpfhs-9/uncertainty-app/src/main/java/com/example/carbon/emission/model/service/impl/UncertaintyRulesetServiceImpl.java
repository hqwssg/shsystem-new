package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.UncertaintyDimensionRuleDto;
import com.example.carbon.emission.model.dto.UncertaintyDimensionSetDto;
import com.example.carbon.emission.model.dto.UncertaintyRulesetCreateRequest;
import com.example.carbon.emission.model.dto.UncertaintyRulesetDto;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.repository.UncertaintyDimensionRuleRepository;
import com.example.carbon.emission.model.repository.UncertaintyRulesetRepository;
import com.example.carbon.emission.model.service.UncertaintyRulesetService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * DQI 规则库服务实现
 * <p>
 * 默认规则库内容（维度判据、entries、band 分段、缺失策略）严格照抄
 * 技术规范 5.9 节 JSON 示例；治理校验规则对应 5.9 治理规则第 1-6 条
 * 及 7.2 阻断类校验。
 */
@Service
@Transactional(readOnly = true)
public class UncertaintyRulesetServiceImpl implements UncertaintyRulesetService {

    private static final Logger log = LoggerFactory.getLogger(UncertaintyRulesetServiceImpl.class);

    /**
     * 内置默认规则库版本号
     */
    public static final String DEFAULT_RULESET_VERSION = "DQI-RULES-2026.12";

    /**
     * 规则库版本 Repository
     */
    @Autowired
    private UncertaintyRulesetRepository rulesetRepository;

    /**
     * 维度规则 Repository
     */
    @Autowired
    private UncertaintyDimensionRuleRepository dimensionRuleRepository;

    /**
     * Jackson 序列化器，用于 entries/validRange 等 JSON 列读写
     */
    @Autowired
    private ObjectMapper objectMapper;

    @Override
    @Transactional
    public Long ensureDefaultRuleset() {
        List<UncertaintyRuleset> existing = rulesetRepository.findAll();
        if (!existing.isEmpty()) {
            return existing.get(0).getId();
        }
        log.info("规则库为空，创建内置默认规则库 {}", DEFAULT_RULESET_VERSION);
        return createRuleset(buildDefaultRulesetRequest());
    }

    @Override
    @Transactional
    public Long createRuleset(UncertaintyRulesetCreateRequest request) {
        if (request == null || request.getRulesetVersion() == null || request.getRulesetVersion().isBlank()) {
            throw new IllegalArgumentException("规则库版本号不能为空");
        }
        // 阻断校验：同版本号重复创建
        if (rulesetRepository.existsByRulesetVersion(request.getRulesetVersion())) {
            throw new IllegalArgumentException("规则库版本号已存在：" + request.getRulesetVersion());
        }
        List<UncertaintyDimensionRuleDto> dims = request.getDimensions();
        if (dims == null || dims.isEmpty()) {
            throw new IllegalArgumentException("规则库 " + request.getRulesetVersion() + " 缺少维度规则");
        }

        // 阻断校验：dimension_weights 中存在维度权重 < 0（W20）
        validateDimensionWeights(request.getDimensionWeights(), request.getRulesetVersion());

        // 逐维度校验 + 按 param_type 聚合
        Map<String, Set<String>> dimCodesByType = new HashMap<>();
        Map<String, Integer> enabledCountByType = new HashMap<>();
        for (UncertaintyDimensionRuleDto dim : dims) {
            String loc = "维度规则[" + dim.getAppliesTo() + "/" + dim.getDimCode() + "]";
            // 阻断校验：applies_to 非 AD/EF 单值
            if (!"AD".equals(dim.getAppliesTo()) && !"EF".equals(dim.getAppliesTo())) {
                throw new IllegalArgumentException(loc + " applies_to 必须为 AD 或 EF 单值，实际为：" + dim.getAppliesTo());
            }
            if (dim.getDimCode() == null || dim.getDimCode().isBlank()) {
                throw new IllegalArgumentException(loc + " dim_code 不能为空");
            }
            // 阻断校验：dim_code 在同一 param_type 内重复
            if (!dimCodesByType.computeIfAbsent(dim.getAppliesTo(), k -> new HashSet<>()).add(dim.getDimCode())) {
                throw new IllegalArgumentException(loc + " dim_code 在同一 param_type 内重复：" + dim.getDimCode());
            }
            // 权重非负（与 W20 同理，单维度条目显式权重也须 ≥0）
            if (dim.getWeight() != null && dim.getWeight().signum() < 0) {
                throw new IllegalArgumentException(loc + " 权重必须非负（W20），实际为：" + dim.getWeight());
            }
            // 阻断校验：null_policy=neutral 但未配 neutral_when_value
            if ("neutral".equals(dim.getNullPolicy())
                    && (dim.getNeutralWhenValue() == null || dim.getNeutralWhenValue().isBlank())) {
                throw new IllegalArgumentException(loc + " null_policy=neutral 但未配置 neutral_when_value");
            }
            // 阻断校验：band 分段连续性/重叠/覆盖 valid_range 全域
            if ("band".equals(dim.getRuleType())) {
                validateBand(dim, loc);
            }
            int enabled = dim.getEnabled() == null ? 1 : dim.getEnabled();
            BigDecimal weight = dim.getWeight() == null ? BigDecimal.ONE : dim.getWeight();
            if (enabled == 1 && weight.signum() > 0) {
                enabledCountByType.merge(dim.getAppliesTo(), 1, Integer::sum);
            }
        }
        // 阻断校验：某 param_type 启用维度数 < 3
        for (Map.Entry<String, Set<String>> e : dimCodesByType.entrySet()) {
            int enabledCount = enabledCountByType.getOrDefault(e.getKey(), 0);
            if (enabledCount < 3) {
                throw new IllegalArgumentException("param_type=" + e.getKey() + " 启用（enabled且weight>0）维度数="
                        + enabledCount + "，少于 3 个，维度过少使归一化失去意义");
            }
        }

        // 落库规则库版本
        UncertaintyRuleset ruleset = new UncertaintyRuleset();
        ruleset.setRulesetVersion(request.getRulesetVersion());
        ruleset.setEffectiveDate(request.getEffectiveDate());
        ruleset.setReviewer(request.getReviewer());
        ruleset.setChangeReason(request.getChangeReason());
        ruleset.setCreatedBy(request.getCreatedBy());
        ruleset.setDimensionWeights(toJson(request.getDimensionWeights()));
        ruleset.setCalibrationMeta(toJson(request.getCalibrationMeta()));
        ruleset.setDeltaTable(toJson(request.getDeltaTable()));
        if (request.getCoverageDeltaCap() != null) {
            ruleset.setCoverageDeltaCap(request.getCoverageDeltaCap());
        }
        if (request.getCoverageAlpha() != null) {
            ruleset.setCoverageAlpha(request.getCoverageAlpha());
        }
        ruleset = rulesetRepository.save(ruleset);

        // 落库维度规则
        List<UncertaintyDimensionRule> entities = new ArrayList<>();
        for (UncertaintyDimensionRuleDto dim : dims) {
            UncertaintyDimensionRule entity = new UncertaintyDimensionRule();
            entity.setRulesetId(ruleset.getId());
            entity.setAppliesTo(dim.getAppliesTo());
            entity.setDimCode(dim.getDimCode());
            entity.setDimName(dim.getDimName());
            entity.setEnabled(dim.getEnabled() == null ? 1 : dim.getEnabled());
            entity.setWeight(dim.getWeight() == null ? BigDecimal.ONE : dim.getWeight());
            entity.setDriver(dim.getDriver());
            entity.setRuleType(dim.getRuleType());
            entity.setEntries(toJson(dim.getEntries()));
            entity.setNullPolicy(dim.getNullPolicy() == null ? "to_manual" : dim.getNullPolicy());
            entity.setNeutralScore(dim.getNeutralScore());
            entity.setNeutralWhenValue(dim.getNeutralWhenValue());
            entity.setDefaultValue(dim.getDefaultValue());
            entity.setMarkDefaultFilled(dim.getMarkDefaultFilled() == null ? 0 : dim.getMarkDefaultFilled());
            entity.setValidRange(toJson(dim.getValidRange()));
            entity.setOutOfRangeWarning(dim.getOutOfRangeWarning());
            entities.add(entity);
        }
        dimensionRuleRepository.saveAll(entities);
        log.info("新建规则库版本 {} 成功，共 {} 个维度规则", request.getRulesetVersion(), entities.size());
        return ruleset.getId();
    }

    @Override
    public UncertaintyRulesetDto getRuleset(String version) {
        UncertaintyRuleset ruleset = rulesetRepository.findByRulesetVersion(version)
                .orElseThrow(() -> new IllegalArgumentException("规则库版本不存在：" + version));
        UncertaintyRulesetDto dto = toDto(ruleset);
        List<UncertaintyDimensionRuleDto> dims = dimensionRuleRepository.findByRulesetId(ruleset.getId())
                .stream().map(this::toDto).toList();
        dto.setDimensions(dims);
        return dto;
    }

    @Override
    public List<UncertaintyRulesetDto> listRulesets() {
        return rulesetRepository.findAll().stream().map(this::toDto).toList();
    }

    @Override
    public UncertaintyRuleset getRulesetEntity(String version) {
        return rulesetRepository.findByRulesetVersion(version)
                .orElseThrow(() -> new IllegalArgumentException("规则库版本不存在：" + version));
    }

    @Override
    public UncertaintyRuleset getLatestRuleset() {
        return rulesetRepository.findAll().stream()
                .max(Comparator.comparing(UncertaintyRuleset::getId))
                .orElseThrow(() -> new IllegalStateException("规则库不存在，请先初始化规则库版本"));
    }

    @Override
    public UncertaintyDimensionSetDto getDimensionSet(String version, String paramType) {
        if (!"AD".equals(paramType) && !"EF".equals(paramType)) {
            throw new IllegalArgumentException("paramType 必须为 AD 或 EF，实际为：" + paramType);
        }
        UncertaintyRuleset ruleset = getRulesetEntity(version);
        List<UncertaintyDimensionRule> rules = dimensionRuleRepository
                .findByRulesetIdAndAppliesTo(ruleset.getId(), paramType);

        // 组装启用维度清单；∑Qmin_w=Σw 仅统计 weight>0 的启用维度
        List<UncertaintyDimensionSetDto.DimItem> items = new ArrayList<>();
        BigDecimal sumW = BigDecimal.ZERO;
        for (UncertaintyDimensionRule rule : rules) {
            int enabled = rule.getEnabled() == null ? 1 : rule.getEnabled();
            if (enabled != 1) {
                continue;
            }
            BigDecimal weight = rule.getWeight() == null ? BigDecimal.ONE : rule.getWeight();
            UncertaintyDimensionSetDto.DimItem item = new UncertaintyDimensionSetDto.DimItem();
            item.setDimCode(rule.getDimCode());
            item.setDimName(rule.getDimName());
            item.setWeight(weight);
            item.setEnabled(enabled);
            items.add(item);
            if (weight.signum() > 0) {
                sumW = sumW.add(weight);
            }
        }
        UncertaintyDimensionSetDto dto = new UncertaintyDimensionSetDto();
        dto.setRulesetVersion(ruleset.getRulesetVersion());
        dto.setParamType(paramType);
        dto.setDimensions(items);
        dto.setSumQMinW(sumW);
        dto.setSumQMaxW(sumW.multiply(BigDecimal.valueOf(5)));
        return dto;
    }

    /**
     * 校验 dimension_weights 中各 param_type 的维度权重均非负（W20 阻断）
     *
     * @param weightsNode    dimension_weights JSON
     * @param rulesetVersion 规则库版本号（用于错误定位）
     */
    private void validateDimensionWeights(JsonNode weightsNode, String rulesetVersion) {
        if (weightsNode == null || !weightsNode.isObject()) {
            return;
        }
        weightsNode.fields().forEachRemaining(ptEntry -> {
            JsonNode ptNode = ptEntry.getValue();
            if (ptNode == null || !ptNode.isObject()) {
                return;
            }
            ptNode.fields().forEachRemaining(dimEntry -> {
                JsonNode w = dimEntry.getValue();
                if (w != null && w.isNumber() && w.doubleValue() < 0) {
                    throw new IllegalArgumentException("规则库 " + rulesetVersion + " dimension_weights."
                            + ptEntry.getKey() + "." + dimEntry.getKey() + " 权重 < 0（W20 阻断），实际为：" + w.doubleValue());
                }
            });
        });
    }

    /**
     * 校验 band 规则分段：entries 为 [[下界(含),上界(不含),分值],...]，
     * 分段必须连续、不重叠，且覆盖 valid_range 全域（valid_range 缺省时
     * 按 entries 的最小下界与最大上界推定）
     *
     * @param dim 维度规则 DTO
     * @param loc 错误定位前缀
     */
    private void validateBand(UncertaintyDimensionRuleDto dim, String loc) {
        JsonNode entries = dim.getEntries();
        if (entries == null || !entries.isArray() || entries.isEmpty()) {
            throw new IllegalArgumentException(loc + " band 规则的 entries 必须为非空数组 [[下界,上界,分值],...]");
        }
        List<double[]> bands = new ArrayList<>();
        for (JsonNode e : entries) {
            if (!e.isArray() || e.size() != 3 || !e.get(0).isNumber() || !e.get(1).isNumber()) {
                throw new IllegalArgumentException(loc + " band 分段格式非法，应为 [下界,上界,分值]：" + e);
            }
            double lo = e.get(0).asDouble();
            double hi = e.get(1).asDouble();
            if (lo >= hi) {
                throw new IllegalArgumentException(loc + " band 分段下界须小于上界：[" + lo + "," + hi + ")");
            }
            bands.add(new double[]{lo, hi});
        }
        bands.sort(Comparator.comparingDouble(b -> b[0]));
        for (int i = 1; i < bands.size(); i++) {
            double prevHi = bands.get(i - 1)[1];
            double lo = bands.get(i)[0];
            if (Double.compare(lo, prevHi) != 0) {
                throw new IllegalArgumentException(loc + " band 分段不连续或重叠：上一段上界=" + prevHi
                        + "，下一段下界=" + lo);
            }
        }
        // 解析 valid_range：缺省时按 entries 的最小下界与最大上界推定
        double rangeLo = bands.get(0)[0];
        double rangeHi = bands.get(bands.size() - 1)[1];
        JsonNode validRange = dim.getValidRange();
        if (validRange != null && validRange.isArray() && validRange.size() == 2) {
            rangeLo = validRange.get(0).asDouble();
            rangeHi = validRange.get(1).asDouble();
        }
        if (bands.get(0)[0] > rangeLo || bands.get(bands.size() - 1)[1] < rangeHi) {
            throw new IllegalArgumentException(loc + " band 分段未覆盖 valid_range 全域 [" + rangeLo + "," + rangeHi
                    + "]：实际覆盖 [" + bands.get(0)[0] + "," + bands.get(bands.size() - 1)[1] + ")");
        }
    }

    /**
     * 组装内置默认规则库请求（内容严格照抄规范 5.9 JSON 示例）
     *
     * @return 默认规则库创建请求
     */
    private UncertaintyRulesetCreateRequest buildDefaultRulesetRequest() {
        UncertaintyRulesetCreateRequest request = new UncertaintyRulesetCreateRequest();
        request.setRulesetVersion(DEFAULT_RULESET_VERSION);
        request.setEffectiveDate(LocalDate.of(2026, 12, 1));
        request.setDimensionWeights(readTree(
                "{\"AD\":{\"A1\":1.0,\"A2\":1.0,\"A4\":1.0,\"A5\":1.0,\"A6\":1.0},"
                        + "\"EF\":{\"E1\":1.0,\"E2\":1.0,\"E3\":1.0,\"E4\":1.0,\"E5\":1.0,\"E6\":1.0}}"));
        request.setDeltaTable(readTree(
                "{\"5.0\":5,\"4.5\":8,\"4.0\":12,\"3.5\":16,\"3.0\":20,\"2.5\":30,"
                        + "\"2.0\":40,\"1.5\":60,\"1.0\":100}"));
        request.setCoverageDeltaCap(new BigDecimal("30"));
        request.setCoverageAlpha(new BigDecimal("15"));
        request.setChangeReason("内置默认规则库");

        List<UncertaintyDimensionRuleDto> dims = new ArrayList<>();
        dims.add(mappingDim("AD", "A1", "计量来源可靠性", "ad_metering_tier", "to_manual",
                "{\"online_meter\":5,\"manual_ledger\":4,\"statistical_report\":3,"
                        + "\"literature_thirdparty\":2,\"default_or_estimated\":1}"));
        UncertaintyDimensionRuleDto a2 = mappingDim("AD", "A2", "计量器具有效性", "ad_meter_calibration", "neutral",
                "{\"calib_valid_cert\":5,\"calib_valid_internal\":4,\"calib_overdue_verified\":3,"
                        + "\"calib_overdue_no_record\":2,\"calib_status_unknown\":1}");
        a2.setNeutralScore(3);
        a2.setNeutralWhenValue("calib_not_applicable");
        dims.add(a2);
        UncertaintyDimensionRuleDto a4 = mappingDim("AD", "A4", "分摊与边界匹配", "ad_geo_basis", "default_with_flag",
                "{\"direct_metered\":5,\"ledger_complete\":4,\"allocated\":3,\"analogized\":2,\"default_value\":1}");
        a4.setDefaultValue("direct_metered");
        a4.setMarkDefaultFilled(1);
        dims.add(a4);
        dims.add(bandDim("AD", "A5", "时间同步性",
                "[[-99,1,5],[1,2,4],[2,3,3],[3,4,2],[4,999,1]]", "[0,999]",
                "Δt<0：数据年份晚于核算年度，逻辑异常，须核实 ad_data_year 或 calc_year"));
        UncertaintyDimensionRuleDto a6 = new UncertaintyDimensionRuleDto();
        a6.setAppliesTo("AD");
        a6.setDimCode("A6");
        a6.setDimName("数据采集质量");
        a6.setEnabled(1);
        a6.setWeight(BigDecimal.ONE);
        a6.setDriver("ad_data_collection_quality");
        a6.setRuleType("direct_score");
        a6.setNullPolicy("to_manual");
        a6.setEntries(readTree("{}"));
        dims.add(a6);

        dims.add(mappingDim("EF", "E1", "来源权威性", "ef_source_authority", "to_manual",
                "{\"official_national\":5,\"national_standard\":4,\"ipcc_default\":3,"
                        + "\"authoritative_literature\":2,\"general_or_estimated\":1}"));
        dims.add(mappingDim("EF", "E2", "组分完整性", "ef_completeness_scope", "to_manual",
                "{\"full\":5,\"minor_missing\":4,\"partial_missing\":3,\"major_only\":2,\"unknown\":1}"));
        dims.add(mappingDim("EF", "E3", "地理适用性", "ef_data_region", "to_manual",
                "{\"in_boundary\":5,\"same_grid\":4,\"national\":3,\"similar_economy\":2,\"other_country\":1}"));
        dims.add(bandDim("EF", "E4", "时间适用性",
                "[[-99,3,5],[3,4,4],[4,5,3],[5,6,2],[6,999,1]]", "[0,999]",
                "Δt<0：因子年份晚于核算年度，逻辑异常，须核实 ef_data_year 或 calc_year"));
        dims.add(mappingDim("EF", "E5", "技术工况适用性", "ef_tech_applicability", "to_manual",
                "{\"same_equipment_condition\":5,\"railway_same_traction\":4,\"railway_generic\":3,"
                        + "\"adjacent_industry\":2,\"generic_default\":1}"));
        dims.add(mappingDim("EF", "E6", "单位换算链可靠性", "ef_conversion_chain", "to_manual",
                "{\"direct_match\":5,\"standard_single\":4,\"multi_step\":3,\"derived_from_other\":2,\"unclear\":1}"));
        request.setDimensions(dims);
        return request;
    }

    /**
     * 构造 mapping 类型维度规则 DTO（enabled=1、weight=1.0）
     */
    private UncertaintyDimensionRuleDto mappingDim(String appliesTo, String dimCode, String dimName,
                                                   String driver, String nullPolicy, String entriesJson) {
        UncertaintyDimensionRuleDto dim = new UncertaintyDimensionRuleDto();
        dim.setAppliesTo(appliesTo);
        dim.setDimCode(dimCode);
        dim.setDimName(dimName);
        dim.setEnabled(1);
        dim.setWeight(BigDecimal.ONE);
        dim.setDriver(driver);
        dim.setRuleType("mapping");
        dim.setNullPolicy(nullPolicy);
        dim.setEntries(readTree(entriesJson));
        return dim;
    }

    /**
     * 构造 band 类型维度规则 DTO（driver=delta_year、null_policy=to_manual）
     */
    private UncertaintyDimensionRuleDto bandDim(String appliesTo, String dimCode, String dimName,
                                                String entriesJson, String validRangeJson,
                                                String outOfRangeWarning) {
        UncertaintyDimensionRuleDto dim = new UncertaintyDimensionRuleDto();
        dim.setAppliesTo(appliesTo);
        dim.setDimCode(dimCode);
        dim.setDimName(dimName);
        dim.setEnabled(1);
        dim.setWeight(BigDecimal.ONE);
        dim.setDriver("delta_year");
        dim.setRuleType("band");
        dim.setNullPolicy("to_manual");
        dim.setEntries(readTree(entriesJson));
        dim.setValidRange(readTree(validRangeJson));
        dim.setOutOfRangeWarning(outOfRangeWarning);
        return dim;
    }

    /**
     * 实体转 DTO（JSON 列反序列化为 JsonNode）
     */
    private UncertaintyRulesetDto toDto(UncertaintyRuleset entity) {
        UncertaintyRulesetDto dto = new UncertaintyRulesetDto();
        dto.setId(entity.getId());
        dto.setRulesetVersion(entity.getRulesetVersion());
        dto.setEffectiveDate(entity.getEffectiveDate());
        dto.setReviewer(entity.getReviewer());
        dto.setDimensionWeights(readTree(entity.getDimensionWeights()));
        dto.setCalibrationMeta(readTree(entity.getCalibrationMeta()));
        dto.setDeltaTable(readTree(entity.getDeltaTable()));
        dto.setCoverageDeltaCap(entity.getCoverageDeltaCap());
        dto.setCoverageAlpha(entity.getCoverageAlpha());
        dto.setChangeReason(entity.getChangeReason());
        dto.setCreatedBy(entity.getCreatedBy());
        dto.setCreatedAt(entity.getCreatedAt());
        return dto;
    }

    /**
     * 维度规则实体转 DTO（entries/validRange 反序列化为 JsonNode）
     */
    private UncertaintyDimensionRuleDto toDto(UncertaintyDimensionRule entity) {
        UncertaintyDimensionRuleDto dto = new UncertaintyDimensionRuleDto();
        dto.setId(entity.getId());
        dto.setAppliesTo(entity.getAppliesTo());
        dto.setDimCode(entity.getDimCode());
        dto.setDimName(entity.getDimName());
        dto.setEnabled(entity.getEnabled());
        dto.setWeight(entity.getWeight());
        dto.setDriver(entity.getDriver());
        dto.setRuleType(entity.getRuleType());
        dto.setEntries(readTree(entity.getEntries()));
        dto.setNullPolicy(entity.getNullPolicy());
        dto.setNeutralScore(entity.getNeutralScore());
        dto.setNeutralWhenValue(entity.getNeutralWhenValue());
        dto.setDefaultValue(entity.getDefaultValue());
        dto.setMarkDefaultFilled(entity.getMarkDefaultFilled());
        dto.setValidRange(readTree(entity.getValidRange()));
        dto.setOutOfRangeWarning(entity.getOutOfRangeWarning());
        return dto;
    }

    /**
     * JsonNode 序列化为 JSON 字符串（null 透传）
     */
    private String toJson(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(node);
        } catch (Exception e) {
            throw new IllegalArgumentException("JSON 序列化失败：" + e.getMessage(), e);
        }
    }

    /**
     * JSON 字符串反序列化为 JsonNode（空串/null 返回 null）
     */
    private JsonNode readTree(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readTree(json);
        } catch (Exception e) {
            throw new IllegalStateException("规则库 JSON 列反序列化失败：" + e.getMessage(), e);
        }
    }
}
