package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.DqiDimSuggestionDto;
import com.example.carbon.emission.model.dto.DqiScoreSubmitItem;
import com.example.carbon.emission.model.dto.DqiScoreSubmitRequest;
import com.example.carbon.emission.model.dto.DqiSuggestionDto;
import com.example.carbon.emission.model.dto.UncertaintyAuditDto;
import com.example.carbon.emission.model.dto.UncertaintySourceMetaUpdateRequest;
import com.example.carbon.emission.model.entity.CalculationNode;
import com.example.carbon.emission.model.entity.CalculationNodeData;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.UncertaintyAudit;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.repository.CalculationNodeDataRepository;
import com.example.carbon.emission.model.repository.CalculationNodeRepository;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.UncertaintyAuditRepository;
import com.example.carbon.emission.model.repository.UncertaintyDimensionRuleRepository;
import com.example.carbon.emission.model.repository.UncertaintyRulesetRepository;
import com.example.carbon.emission.model.repository.UncertaintyScoreRepository;
import com.example.carbon.emission.model.repository.UncertaintySourceMetaRepository;
import com.example.carbon.emission.model.service.DqiScoringService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * DQI 自动评分引擎实现（M2a + I1 + I2 + O6）
 * <p>
 * 评分算法严格对应技术规范 5.8.1 五步框架（V2.0 简化）：
 * 固定维度集（AD→A1/A2/A4/A5/A6，EF→E1-E6）、mapping/band/direct_score
 * 三种规则求值、A6 excluded 类中性 3 分、缺失转人工（禁止默认分填充，
 * 仅 ad_geo_basis 留空默认填充与 calib_not_applicable 中性分两条例外）、
 * 软校验 W1-W3、W9-W13。
 */
@Service
@Transactional(readOnly = true)
public class DqiScoringServiceImpl implements DqiScoringService {

    private static final Logger log = LoggerFactory.getLogger(DqiScoringServiceImpl.class);

    /**
     * AD 固定维度集（规范 5.8.1 第 1 步）
     */
    private static final List<String> AD_DIMS = List.of("A1", "A2", "A4", "A5", "A6");

    /**
     * EF 固定维度集（规范 5.8.1 第 1 步）
     */
    private static final List<String> EF_DIMS = List.of("E1", "E2", "E3", "E4", "E5", "E6");

    /**
     * A6 excluded 类计量层级（纯估算、无计量周期概念，规范 5.8.1 第 3 步）
     */
    private static final Set<String> A6_EXCLUDED_TIERS =
            Set.of("statistical_report", "literature_thirdparty", "default_or_estimated");

    /**
     * 软校验警告文本（规范 5.8.4）
     */
    private static final String W1_TEXT = "W1:估算/缺省来源不应存在计量器具状态，字段填写疑似矛盾";
    private static final String W2_TEXT = "W2:在线计量必有计量器具，不应标记为不适用";
    private static final String W3_TEXT = "W3:来自文献/估算的数据不可能是边界内直接计量";
    private static final String W9_TEXT = "W9:来源可靠性低但器具状态优，判定依据可能不一致，请复核";
    private static final String W10_TEXT = "W10:来源为一般文献/自行估算，权威性高分需说明依据";
    private static final String W11_TEXT = "W11:通用缺省值，技术工况适用性高分需说明依据";
    private static final String W13_TEXT = "W13:排放因子整体依赖低权威来源或换算路径不明，提示补充官方因子";

    @Autowired
    private UncertaintySourceMetaRepository sourceMetaRepository;

    @Autowired
    private UncertaintyScoreRepository scoreRepository;

    @Autowired
    private UncertaintyAuditRepository auditRepository;

    @Autowired
    private UncertaintyRulesetRepository rulesetRepository;

    @Autowired
    private UncertaintyDimensionRuleRepository dimensionRuleRepository;

    @Autowired
    private CalculationTemplateRepository calculationTemplateRepository;

    @Autowired
    private CalculationNodeRepository calculationNodeRepository;

    @Autowired
    private CalculationNodeDataRepository calculationNodeDataRepository;

    @Autowired
    private EmissionNodeRepository emissionNodeRepository;

    @Autowired
    private NamedParameterJdbcTemplate namedJdbc;

    @Autowired
    private ObjectMapper objectMapper;

    @Override
    @Transactional
    public int importSources(Long calculationTemplateId, Integer calcYear) {
        CalculationTemplate template = calculationTemplateRepository.findById(calculationTemplateId)
                .orElseThrow(() -> new IllegalArgumentException("核算任务不存在：id=" + calculationTemplateId));
        // 核算年度推定（calcYear 为空时取核算周期结束日期年份），此处仅校验可推定
        resolveCalcYear(template, calcYear);

        // 步骤1：拉取该核算任务的节点快照与采集节点核算数据
        List<CalculationNode> nodes = calculationNodeRepository.findByCalculationTemplateId(calculationTemplateId);
        if (nodes.isEmpty()) {
            log.info("核算任务 {} 无节点快照，导入 0 条排放源", calculationTemplateId);
            return 0;
        }
        Map<Long, CalculationNode> nodeMap = nodes.stream()
                .collect(Collectors.toMap(CalculationNode::getId, Function.identity()));
        List<CalculationNodeData> dataList = calculationNodeDataRepository.findByCalculationNodeIdIn(nodeMap.keySet());

        // 步骤2：经 CalculationNode.nodeId → EmissionNode.name 预取节点名称
        Set<Long> sourceNodeIds = nodes.stream().map(CalculationNode::getNodeId).collect(Collectors.toSet());
        Map<Long, String> nameMap = emissionNodeRepository.findAllById(sourceNodeIds).stream()
                .collect(Collectors.toMap(EmissionNode::getId, EmissionNode::getName));

        // 步骤2b：预取节点→采集点配置（emission_node_config）与采集点表固化的 DQI 驱动字段
        // （emission_meter_info / emission_fossil_fuel_meter_info / emission_purchased_heat_meter_info），
        // 用于把采集点级评分信息带入排放源，实现"核算后沿用自动评分"
        Map<Long, List<NodeConfig>> configMap = loadNodeConfigs(sourceNodeIds);
        Map<String, MeterDqi> meterDqiMap = loadMeterDqiFields(configMap);

        // 步骤3：幂等 upsert（仅刷新名义值快照字段，不覆盖人工补录的 ad_*/ef_* 元信息）
        int count = 0;
        for (CalculationNodeData data : dataList) {
            CalculationNode node = nodeMap.get(data.getCalculationNodeId());
            Long sourceNodeId = node != null ? node.getNodeId() : null;
            String sourceName = sourceNodeId != null
                    ? nameMap.getOrDefault(sourceNodeId, "节点#" + sourceNodeId)
                    : "节点#" + data.getCalculationNodeId();
            // adjusted 修正值非空时优先取修正值，否则取原始计量/计算值
            BigDecimal adValue = data.getAdjustedEnergyValue() != null
                    ? data.getAdjustedEnergyValue() : data.getEnergyMeasurementValue();
            BigDecimal emissionValue = data.getAdjustedCarbonEmission() != null
                    ? data.getAdjustedCarbonEmission() : data.getCarbonEmission();

            UncertaintySourceMeta meta = sourceMetaRepository
                    .findByCalculationTemplateIdAndCollectionNodeDataId(calculationTemplateId, data.getId())
                    .orElseGet(UncertaintySourceMeta::new);
            meta.setCalculationTemplateId(calculationTemplateId);
            meta.setCollectionNodeDataId(data.getId());
            meta.setSourceNodeId(sourceNodeId);
            meta.setSourceName(sourceName);
            meta.setScope(data.getEmissionCategory());
            meta.setEmissionSubcategory(data.getEmissionSubcategory());
            meta.setAdValue(adValue);
            meta.setAdUnit(data.getMeasurementUnit());
            meta.setEfValue(data.getCarbonEmissionFactor());
            meta.setEmissionValue(emissionValue);
            // 采集点固化的 DQI 驱动字段带入（仅在源级字段为空时填充，不覆盖人工补录值）
            fillMeterDqi(meta, configMap.get(sourceNodeId), data, meterDqiMap);
            sourceMetaRepository.save(meta);
            count++;
        }
        log.info("核算任务 {} 导入/更新排放源元信息 {} 条", calculationTemplateId, count);
        return count;
    }

    /**
     * 加载排放节点的采集点配置（emission_node_config 只读）。
     * collection_point_type：1-电表，2-化石燃料，3-外购热能
     */
    private Map<Long, List<NodeConfig>> loadNodeConfigs(Set<Long> nodeIds) {
        if (nodeIds == null || nodeIds.isEmpty()) {
            return Map.of();
        }
        String sql = "SELECT node_id, emission_subcategory, collection_point_type, collection_point_id"
                + " FROM emission_node_config WHERE node_id IN (:ids)"
                + " AND collection_point_type IS NOT NULL AND collection_point_id IS NOT NULL";
        List<NodeConfig> rows = namedJdbc.query(sql, Map.of("ids", nodeIds), (rs, i) -> {
            NodeConfig c = new NodeConfig();
            c.nodeId = rs.getLong("node_id");
            c.emissionSubcategory = rs.getString("emission_subcategory");
            c.pointType = rs.getInt("collection_point_type");
            c.pointId = rs.getLong("collection_point_id");
            return c;
        });
        return rows.stream().collect(Collectors.groupingBy(c -> c.nodeId));
    }

    /**
     * 按采集点类型分表批量加载固化的 DQI 驱动字段，key 为 "type:pointId"
     */
    private Map<String, MeterDqi> loadMeterDqiFields(Map<Long, List<NodeConfig>> configMap) {
        Map<Integer, Set<Long>> idsByType = new HashMap<>();
        for (List<NodeConfig> list : configMap.values()) {
            for (NodeConfig c : list) {
                idsByType.computeIfAbsent(c.pointType, k -> new HashSet<>()).add(c.pointId);
            }
        }
        Map<Integer, String> tableByType = Map.of(
                1, "emission_meter_info",
                2, "emission_fossil_fuel_meter_info",
                3, "emission_purchased_heat_meter_info");
        Map<String, MeterDqi> result = new HashMap<>();
        for (Map.Entry<Integer, Set<Long>> e : idsByType.entrySet()) {
            String table = tableByType.get(e.getKey());
            if (table == null || e.getValue().isEmpty()) {
                continue;
            }
            String sql = "SELECT id, ad_metering_tier, ad_meter_calibration, ad_geo_basis,"
                    + " ad_data_collection_quality FROM " + table + " WHERE id IN (:ids)";
            namedJdbc.query(sql, Map.of("ids", e.getValue()), rs -> {
                MeterDqi m = new MeterDqi();
                m.adMeteringTier = rs.getString("ad_metering_tier");
                m.adMeterCalibration = rs.getString("ad_meter_calibration");
                m.adGeoBasis = rs.getString("ad_geo_basis");
                int quality = rs.getInt("ad_data_collection_quality");
                m.adDataCollectionQuality = rs.wasNull() ? null : quality;
                result.put(e.getKey() + ":" + rs.getLong("id"), m);
            });
        }
        return result;
    }

    /**
     * 批量读取核算结果行快照（emission_collection_node_data）：
     * 10 个 DQI 评分 + 采集记录截止日期（A5 时间同步性驱动）。
     * 评分有值（1-5）时沿用；缺失维度回退规则库自动求值；
     * 记录不存在则整个 snapshot 为 null。
     */
    private Map<Long, NodeSnapshot> loadNodeScores(List<UncertaintySourceMeta> sources) {
        Set<Long> ids = sources.stream().map(UncertaintySourceMeta::getCollectionNodeDataId)
                .filter(Objects::nonNull).collect(Collectors.toSet());
        if (ids.isEmpty()) {
            return Map.of();
        }
        String sql = "SELECT id, collection_record_end_date, dqi_a1_score, dqi_a2_score,"
                + " dqi_a4_score, dqi_a6_score, dqi_e1_score, dqi_e2_score, dqi_e3_score,"
                + " dqi_e4_score, dqi_e5_score, dqi_e6_score"
                + " FROM emission_collection_node_data WHERE id IN (:ids)";
        Map<Long, NodeSnapshot> result = new HashMap<>();
        namedJdbc.query(sql, Map.of("ids", ids), rs -> {
            NodeSnapshot snap = new NodeSnapshot();
            java.sql.Date endDate = rs.getDate("collection_record_end_date");
            snap.endDate = endDate == null ? null : endDate.toLocalDate();
            putScore(snap.scores, rs, "AD|A1", "dqi_a1_score");
            putScore(snap.scores, rs, "AD|A2", "dqi_a2_score");
            putScore(snap.scores, rs, "AD|A4", "dqi_a4_score");
            putScore(snap.scores, rs, "AD|A6", "dqi_a6_score");
            putScore(snap.scores, rs, "EF|E1", "dqi_e1_score");
            putScore(snap.scores, rs, "EF|E2", "dqi_e2_score");
            putScore(snap.scores, rs, "EF|E3", "dqi_e3_score");
            putScore(snap.scores, rs, "EF|E4", "dqi_e4_score");
            putScore(snap.scores, rs, "EF|E5", "dqi_e5_score");
            putScore(snap.scores, rs, "EF|E6", "dqi_e6_score");
            result.put(rs.getLong("id"), snap);
        });
        return result;
    }

    /**
     * 读取可空整型评分字段；值为 NULL 时不写入 map。
     */
    private void putScore(Map<String, Integer> scores, ResultSet rs, String key, String column)
            throws SQLException {
        int value = rs.getInt(column);
        if (!rs.wasNull()) {
            scores.put(key, value);
        }
    }

    /**
     * 将采集点固化的 DQI 驱动字段带入排放源元信息。
     * 匹配规则：同节点下优先 emission_subcategory 精确匹配（核算数据按小类分行），
     * 无匹配时取该节点第一条采集点配置；仅在源级字段为空时填充，不覆盖人工补录值。
     */
    private void fillMeterDqi(UncertaintySourceMeta meta, List<NodeConfig> configs,
                              CalculationNodeData data, Map<String, MeterDqi> meterDqiMap) {
        if (configs == null || configs.isEmpty()) {
            return;
        }
        NodeConfig chosen = configs.stream()
                .filter(c -> c.emissionSubcategory != null
                        && c.emissionSubcategory.equals(data.getEmissionSubcategory()))
                .findFirst()
                .orElse(configs.get(0));
        MeterDqi m = meterDqiMap.get(chosen.pointType + ":" + chosen.pointId);
        if (m == null) {
            return;
        }
        if (isBlank(meta.getAdMeteringTier()) && !isBlank(m.adMeteringTier)) {
            meta.setAdMeteringTier(m.adMeteringTier);
        }
        if (isBlank(meta.getAdMeterCalibration()) && !isBlank(m.adMeterCalibration)) {
            meta.setAdMeterCalibration(m.adMeterCalibration);
        }
        if (isBlank(meta.getAdGeoBasis()) && !isBlank(m.adGeoBasis)) {
            meta.setAdGeoBasis(m.adGeoBasis);
        }
        if (meta.getAdDataCollectionQuality() == null && m.adDataCollectionQuality != null) {
            meta.setAdDataCollectionQuality(m.adDataCollectionQuality);
        }
    }

    private static boolean isBlank(String v) {
        return v == null || v.isBlank();
    }

    /**
     * 排放节点采集点配置（emission_node_config 只读视图）
     */
    private static class NodeConfig {
        Long nodeId;
        String emissionSubcategory;
        Integer pointType;
        Long pointId;
    }

    /**
     * 采集点表固化的 DQI 驱动字段
     */
    private static class MeterDqi {
        String adMeteringTier;
        String adMeterCalibration;
        String adGeoBasis;
        Integer adDataCollectionQuality;
    }

    /**
     * 核算结果行快照：DQI 评分 map + 采集记录截止日期（A5 时间同步性驱动）
     */
    private static class NodeSnapshot {
        /** paramType|dimCode → 分值（仅写入非空评分） */
        final Map<String, Integer> scores = new HashMap<>();
        /** emission_collection_node_data.collection_record_end_date */
        java.time.LocalDate endDate;
    }

    @Override
    @Transactional
    public void updateSourceMeta(Long metaId, UncertaintySourceMetaUpdateRequest request) {
        UncertaintySourceMeta meta = sourceMetaRepository.findById(metaId)
                .orElseThrow(() -> new IllegalArgumentException("排放源元信息不存在：id=" + metaId));
        // 仅更新请求中非 null 的字段
        if (request.getAdMeteringTier() != null) {
            meta.setAdMeteringTier(request.getAdMeteringTier());
        }
        if (request.getAdMeterCalibration() != null) {
            meta.setAdMeterCalibration(request.getAdMeterCalibration());
        }
        if (request.getAdDataYear() != null) {
            meta.setAdDataYear(request.getAdDataYear());
        }
        if (request.getAdGeoBasis() != null) {
            meta.setAdGeoBasis(request.getAdGeoBasis());
        }
        if (request.getAdDataCollectionQuality() != null) {
            meta.setAdDataCollectionQuality(request.getAdDataCollectionQuality());
        }
        if (request.getEfSourceAuthority() != null) {
            meta.setEfSourceAuthority(request.getEfSourceAuthority());
        }
        if (request.getEfCompletenessScope() != null) {
            meta.setEfCompletenessScope(request.getEfCompletenessScope());
        }
        if (request.getEfDataRegion() != null) {
            meta.setEfDataRegion(request.getEfDataRegion());
        }
        if (request.getEfDataYear() != null) {
            meta.setEfDataYear(request.getEfDataYear());
        }
        if (request.getEfTechApplicability() != null) {
            meta.setEfTechApplicability(request.getEfTechApplicability());
        }
        if (request.getEfConversionChain() != null) {
            meta.setEfConversionChain(request.getEfConversionChain());
        }
        if (request.getDataSource() != null) {
            meta.setDataSource(request.getDataSource());
        }
        if (request.getEnergyType() != null) {
            meta.setEnergyType(request.getEnergyType());
        }
        meta.setUpdatedAt(LocalDateTime.now());
        sourceMetaRepository.save(meta);
    }

    @Override
    public List<UncertaintySourceMeta> listSources(Long calculationTemplateId) {
        return sourceMetaRepository.findByCalculationTemplateId(calculationTemplateId);
    }

    @Override
    public List<UncertaintyScore> getScores(Long sourceMetaId, String paramType) {
        List<UncertaintyScore> rows = scoreRepository.findBySourceMetaId(sourceMetaId);
        if (paramType == null || paramType.isBlank()) {
            return rows;
        }
        // 按参数类型过滤（大小写不敏感）
        return rows.stream()
                .filter(s -> paramType.equalsIgnoreCase(s.getParamType()))
                .collect(Collectors.toList());
    }

    @Override
    @Transactional
    public List<DqiSuggestionDto> generateSuggestions(Long calculationTemplateId, String rulesetVersion,
                                                      Integer calcYear) {
        // rulesetVersion 为空时取最新版本规则库（按ID最大者）
        final String resolvedVersion;
        if (rulesetVersion == null || rulesetVersion.isBlank()) {
            resolvedVersion = rulesetRepository.findAll().stream()
                    .max(Comparator.comparing(UncertaintyRuleset::getId))
                    .orElseThrow(() -> new IllegalStateException("规则库不存在，请先初始化规则库版本"))
                    .getRulesetVersion();
        } else {
            resolvedVersion = rulesetVersion;
        }
        // 步骤1：加载规则库与维度规则、权重
        UncertaintyRuleset ruleset = rulesetRepository.findByRulesetVersion(resolvedVersion)
                .orElseThrow(() -> new IllegalArgumentException("规则库版本不存在：" + resolvedVersion));
        List<UncertaintyDimensionRule> rules = dimensionRuleRepository.findByRulesetId(ruleset.getId());
        Map<String, UncertaintyDimensionRule> adRuleMap = rules.stream()
                .filter(r -> "AD".equals(r.getAppliesTo()))
                .collect(Collectors.toMap(UncertaintyDimensionRule::getDimCode, Function.identity(), (a, b) -> a));
        Map<String, UncertaintyDimensionRule> efRuleMap = rules.stream()
                .filter(r -> "EF".equals(r.getAppliesTo()))
                .collect(Collectors.toMap(UncertaintyDimensionRule::getDimCode, Function.identity(), (a, b) -> a));
        JsonNode weightsNode = readTree(ruleset.getDimensionWeights());

        CalculationTemplate template = calculationTemplateRepository.findById(calculationTemplateId)
                .orElseThrow(() -> new IllegalArgumentException("核算任务不存在：id=" + calculationTemplateId));
        int year = resolveCalcYear(template, calcYear);

        List<UncertaintySourceMeta> sources = sourceMetaRepository.findByCalculationTemplateId(calculationTemplateId);

        // 步骤2a：预取各排放源对应核算结果行（emission_collection_node_data）的 DQI 评分快照，
        // 评分优先沿用核算生成时写入的记录，缺失维度再回退到规则库自动求值
        Map<Long, NodeSnapshot> nodeSnapshots = loadNodeScores(sources);

        // 步骤2：任务级 W13 预计算（同任务全部 EF 均 general_or_estimated，或 unclear 占比>30%）
        boolean w13Hit = false;
        if (!sources.isEmpty()) {
            boolean allGeneral = sources.stream()
                    .allMatch(s -> "general_or_estimated".equals(s.getEfSourceAuthority()));
            long unclearCount = sources.stream()
                    .filter(s -> "unclear".equals(s.getEfConversionChain())).count();
            w13Hit = allGeneral || (double) unclearCount / sources.size() > 0.3;
        }

        // 步骤3：逐排放源对 AD/EF 两组维度评分并 upsert
        List<DqiSuggestionDto> result = new ArrayList<>();
        for (UncertaintySourceMeta source : sources) {
            Map<String, UncertaintyScore> existingRows = scoreRepository.findBySourceMetaId(source.getId())
                    .stream().collect(Collectors.toMap(s -> s.getParamType() + "|" + s.getDimCode(), Function.identity()));

            List<DqiDimSuggestionDto> dimDtos = new ArrayList<>();
            List<String> sourceWarnings = new ArrayList<>();
            NodeSnapshot snapshot = source.getCollectionNodeDataId() == null
                    ? null : nodeSnapshots.get(source.getCollectionNodeDataId());
            Map<String, Integer> nodeScores = snapshot == null ? null : snapshot.scores;
            processParamType(source, "AD", AD_DIMS, adRuleMap, weightsNode, year, resolvedVersion,
                    existingRows, dimDtos, false, snapshot);
            processParamType(source, "EF", EF_DIMS, efRuleMap, weightsNode, year, resolvedVersion,
                    existingRows, dimDtos, w13Hit, snapshot);
            if (w13Hit) {
                sourceWarnings.add(W13_TEXT);
            }

            DqiSuggestionDto dto = new DqiSuggestionDto();
            dto.setSourceMetaId(source.getId());
            dto.setSourceName(source.getSourceName());
            dto.setCalcYear(year);
            dto.setRulesetVersion(resolvedVersion);
            dto.setDimensions(dimDtos);
            dto.setWarnings(sourceWarnings);
            result.add(dto);
        }
        return result;
    }

    @Override
    @Transactional
    public void submitScores(Long sourceMetaId, String paramType, DqiScoreSubmitRequest request, String reviewer) {
        UncertaintySourceMeta meta = sourceMetaRepository.findById(sourceMetaId)
                .orElseThrow(() -> new IllegalArgumentException("排放源元信息不存在：id=" + sourceMetaId));
        if (!"AD".equals(paramType) && !"EF".equals(paramType)) {
            throw new IllegalArgumentException("paramType 必须为 AD 或 EF，实际为：" + paramType);
        }
        if (request == null || request.getItems() == null || request.getItems().isEmpty()) {
            throw new IllegalArgumentException("提交项不能为空");
        }
        List<UncertaintyScore> rows = scoreRepository.findBySourceMetaId(sourceMetaId).stream()
                .filter(s -> paramType.equals(s.getParamType())).collect(Collectors.toList());
        if (rows.isEmpty()) {
            throw new IllegalArgumentException("排放源 " + sourceMetaId + " 的 " + paramType
                    + " 尚未生成建议分，请先执行 M2a 自动评分");
        }
        // 评分永久绑定其 ruleset_version，启用维度集按绑定版本的规则库判定
        String rulesetVersion = rows.get(0).getRulesetVersion();
        UncertaintyRuleset ruleset = rulesetRepository.findByRulesetVersion(rulesetVersion)
                .orElseThrow(() -> new IllegalStateException("评分绑定的规则库版本不存在：" + rulesetVersion));
        Set<String> enabledDims = dimensionRuleRepository.findByRulesetIdAndAppliesTo(ruleset.getId(), paramType)
                .stream()
                .filter(r -> r.getEnabled() != null && r.getEnabled() == 1
                        && r.getWeight() != null && r.getWeight().signum() > 0)
                .map(UncertaintyDimensionRule::getDimCode)
                .collect(Collectors.toSet());
        Map<String, UncertaintyScore> rowMap = rows.stream()
                .collect(Collectors.toMap(UncertaintyScore::getDimCode, Function.identity()));

        // 阻断校验：维度键归属、分值域、manual_override 理由
        for (DqiScoreSubmitItem item : request.getItems()) {
            if (!enabledDims.contains(item.getDimCode())) {
                throw new IllegalArgumentException("维度 " + item.getDimCode() + " 不属于 " + paramType
                        + " 启用维度集 " + enabledDims + "，拒绝提交");
            }
            Integer f = item.getFinalScore();
            if (f == null || f < 1 || f > 5) {
                throw new IllegalArgumentException("维度 " + item.getDimCode()
                        + " 的 final_score 必须为 1-5 整数，实际为：" + f);
            }
            if ("manual_override".equals(item.getScoreSource())
                    && (item.getOverrideReason() == null || item.getOverrideReason().isBlank())) {
                throw new IllegalArgumentException("维度 " + item.getDimCode()
                        + " score_source=manual_override 时 override_reason 必填");
            }
        }

        boolean a6Excluded = "AD".equals(paramType) && meta.getAdMeteringTier() != null
                && A6_EXCLUDED_TIERS.contains(meta.getAdMeteringTier());

        // 提交前建议分状态的 SDQI（W12 基准）
        double sdqiBefore = computeSdqi(rows, false);

        LocalDateTime now = LocalDateTime.now();
        List<UncertaintyAudit> audits = new ArrayList<>();
        for (DqiScoreSubmitItem item : request.getItems()) {
            UncertaintyScore row = rowMap.get(item.getDimCode());
            Integer oldFinal = row.getFinalScore();
            String oldSource = row.getScoreSource();
            Integer newFinal = item.getFinalScore();
            String newSource;
            if ("A6".equals(item.getDimCode()) && a6Excluded) {
                // excluded 类 A6 无论用户填什么都强制回写 3 分
                newFinal = 3;
                newSource = "auto_neutral_excluded";
                row.setA6Source("neutral_excluded");
                if (!Integer.valueOf(3).equals(item.getFinalScore())) {
                    appendRowWarning(row, "excluded 类 A6 值非 3，系统自动覆盖为 3 分并标注 neutral_excluded");
                }
            } else if (item.getScoreSource() != null && !item.getScoreSource().isBlank()) {
                newSource = item.getScoreSource();
            } else {
                // 未显式指定分值来源：与建议分一致记 auto，不一致记 manual_override
                newSource = Objects.equals(newFinal, row.getSuggestedScore()) ? "auto" : "manual_override";
                if ("manual_override".equals(newSource)
                        && (item.getOverrideReason() == null || item.getOverrideReason().isBlank())) {
                    throw new IllegalArgumentException("维度 " + item.getDimCode()
                            + " 最终分与建议分不一致（manual_override），override_reason 必填");
                }
            }
            row.setFinalScore(newFinal);
            row.setScoreSource(newSource);
            row.setOverrideReason(item.getOverrideReason());
            row.setReviewer(reviewer);
            row.setReviewTime(now);
            row.setRulesetVersion(rulesetVersion);
            scoreRepository.save(row);

            // 审计：final_score 变化（含首次填写 old=null）
            if (!Objects.equals(oldFinal, newFinal)) {
                UncertaintyAudit audit = new UncertaintyAudit();
                audit.setScoreId(row.getId());
                audit.setSourceMetaId(sourceMetaId);
                audit.setParamType(paramType);
                audit.setDimCode(item.getDimCode());
                audit.setOldScore(oldFinal);
                audit.setNewScore(newFinal);
                audit.setOldSource(oldSource);
                audit.setNewSource(newSource);
                audit.setOverrideReason(item.getOverrideReason());
                audit.setReviewer(reviewer);
                audit.setReviewTime(now);
                audit.setRulesetVersion(rulesetVersion);
                audits.add(audit);
            }
        }
        // 阻断校验：suggested_score=null 的维度必须人工给 final
        for (UncertaintyScore row : rows) {
            if (enabledDims.contains(row.getDimCode())
                    && row.getSuggestedScore() == null && row.getFinalScore() == null) {
                throw new IllegalArgumentException("维度 " + row.getDimCode()
                        + " 的 suggested_score=null，必须人工给 final 后才能提交");
            }
        }
        // W12：提交后 SDQI 较建议分状态跨档（变动≥0.5）→ 警告写入 warnings
        double sdqiAfter = computeSdqi(rows, true);
        if (!Double.isNaN(sdqiBefore) && !Double.isNaN(sdqiAfter)
                && Math.abs(sdqiAfter - sdqiBefore) >= 0.5) {
            String w12Text = "W12:人工覆盖导致 SDQI 跨档（" + sdqiBefore + "→" + sdqiAfter
                    + "，变动≥0.5），建议复核理由充分性";
            for (UncertaintyScore row : rows) {
                appendRowWarning(row, w12Text);
                scoreRepository.save(row);
            }
        }
        auditRepository.saveAll(audits);
    }

    @Override
    public List<UncertaintyAuditDto> getAudit(Long sourceMetaId) {
        return auditRepository.findBySourceMetaIdOrderByIdDesc(sourceMetaId).stream().map(a -> {
            UncertaintyAuditDto dto = new UncertaintyAuditDto();
            dto.setId(a.getId());
            dto.setScoreId(a.getScoreId());
            dto.setSourceMetaId(a.getSourceMetaId());
            dto.setParamType(a.getParamType());
            dto.setDimCode(a.getDimCode());
            dto.setOldScore(a.getOldScore());
            dto.setNewScore(a.getNewScore());
            dto.setOldSource(a.getOldSource());
            dto.setNewSource(a.getNewSource());
            dto.setOverrideReason(a.getOverrideReason());
            dto.setReviewer(a.getReviewer());
            dto.setReviewTime(a.getReviewTime());
            dto.setRulesetVersion(a.getRulesetVersion());
            return dto;
        }).collect(Collectors.toList());
    }

    /**
     * 处理单排放源单参数类型的整组维度（规范 5.8.1 第 1-4 步）：
     * 求值 → 记录级状态降级 → 软校验 → upsert 评分行 → 组装 DTO
     *
     * @param w13Hit 任务级 W13 是否命中（仅 EF 组使用）
     * @param snapshot 核算结果行快照（评分 map + 采集截止日期）；为空时全部回退规则库求值
     */
    private void processParamType(UncertaintySourceMeta source, String paramType, List<String> dimCodes,
                                  Map<String, UncertaintyDimensionRule> ruleMap, JsonNode weightsNode, int calcYear,
                                  String rulesetVersion, Map<String, UncertaintyScore> existingRows,
                                  List<DqiDimSuggestionDto> dimDtos, boolean w13Hit,
                                  NodeSnapshot snapshot) {
        Map<String, Integer> nodeScores = snapshot == null ? null : snapshot.scores;
        // 第 2-3 步：逐维度求值
        List<DimResult> results = new ArrayList<>();
        for (String dimCode : dimCodes) {
            results.add(scoreDimension(source, paramType, dimCode, ruleMap.get(dimCode), calcYear, snapshot));
        }
        // 第 4 步：记录级有任一 null 则该记录非 complete
        boolean anyNull = results.stream().anyMatch(r -> r.suggested == null);
        // 软校验（W1-W3、W9 用 final（无 final 时用 suggested）判，W10/W11 同理，W13 任务级）
        applySoftWarnings(source, paramType, results, existingRows, w13Hit);

        for (DimResult r : results) {
            String status = anyNull ? "partial" : "complete";
            double weight = weightsNode == null ? 1.0
                    : weightsNode.path(paramType).path(r.dimCode).asDouble(1.0);
            // upsert：保留已有 final_score/reviewer，仅刷新自动评分相关字段
            String key = paramType + "|" + r.dimCode;
            UncertaintyScore row = existingRows.get(key);
            if (row == null) {
                row = new UncertaintyScore();
                row.setSourceMetaId(source.getId());
                row.setParamType(paramType);
                row.setDimCode(r.dimCode);
            }
            row.setWeight(BigDecimal.valueOf(weight));
            row.setSuggestedScore(r.suggested);
            row.setScoreEvidence(r.evidence);
            row.setAutoScoringStatus(status);
            row.setA6Source(r.a6Source);
            row.setDefaultFilled(r.defaultFilled ? 1 : 0);
            row.setWarnings(r.warningTexts.isEmpty() ? null : String.join(",", r.warningTexts));
            row.setRulesetVersion(rulesetVersion);
            if (r.scoreSourcePreview != null) {
                row.setScoreSource(r.scoreSourcePreview);
            }
            scoreRepository.save(row);

            DqiDimSuggestionDto dto = new DqiDimSuggestionDto();
            dto.setParamType(paramType);
            dto.setDimCode(r.dimCode);
            dto.setSuggested(r.suggested);
            dto.setEvidence(r.evidence);
            dto.setStatus(status);
            dto.setA6Source(r.a6Source);
            dto.setDefaultFilled(r.defaultFilled);
            dto.setWarnings(r.warningTexts);
            dimDtos.add(dto);
        }
    }

    /**
     * 单维度求值：核算结果行已有评分时直接沿用；否则按规则类型分发
     * mapping / band / direct_score（A6/A5 特殊处理）
     */
    private DimResult scoreDimension(UncertaintySourceMeta source, String paramType, String dimCode,
                                     UncertaintyDimensionRule rule, int calcYear,
                                     NodeSnapshot snapshot) {
        Map<String, Integer> nodeScores = snapshot == null ? null : snapshot.scores;
        // 优先沿用核算生成阶段写入 emission_collection_node_data 的评分快照
        Integer stored = nodeScores == null ? null : nodeScores.get(paramType + "|" + dimCode);
        if (stored != null && stored >= 1 && stored <= 5) {
            DimResult r = new DimResult(dimCode);
            r.suggested = stored;
            r.evidence = "沿用核算结果记录评分：emission_collection_node_data.dqi_"
                    + dimCode.toLowerCase() + "_score=" + stored;
            if ("A6".equals(dimCode)) {
                r.a6Source = "record_snapshot";
            }
            return r;
        }
        if (rule == null) {
            DimResult r = new DimResult(dimCode);
            r.evidence = "规则库缺少 " + paramType + "/" + dimCode + " 维度规则，转人工必填";
            return r;
        }
        // A5 专用：Δt 基于 emission_collection_node_data.collection_record_end_date 与核算年度
        if ("A5".equals(dimCode) && "band".equals(rule.getRuleType())) {
            return evalA5(source, rule, calcYear, snapshot == null ? null : snapshot.endDate);
        }
        if ("A6".equals(dimCode)) {
            return evalA6(source);
        }
        if ("band".equals(rule.getRuleType())) {
            Integer dataYear = "AD".equals(paramType) ? source.getAdDataYear() : source.getEfDataYear();
            String yearField = "AD".equals(paramType) ? "ad_data_year" : "ef_data_year";
            return evalBand(dimCode, rule, dataYear, calcYear, yearField);
        }
        return evalMapping(dimCode, rule, driverValue(source, paramType, dimCode));
    }

    /**
     * A5 时间同步性专用求值：
     * <ol>
     *   <li>优先级 1：emission_collection_node_data.collection_record_end_date（新口径，采集截止日期所在年）；</li>
     *   <li>优先级 2：UncertaintySourceMeta.ad_data_year（旧口径 fallback，兼容存量未写入 endDate 的场景与单元测试）。</li>
     * </ol>
     * 当驱动缺失或 Δt 不落在规则库 band 定义域内时（含 Δt&lt;0、Δt 过大），
     * suggested=null，由上游按"转人工必填"处理。
     */
    private DimResult evalA5(UncertaintySourceMeta source, UncertaintyDimensionRule rule,
                             int calcYear, java.time.LocalDate endDate) {
        DimResult r = new DimResult("A5");
        Integer dtYear;
        String baseLabel;
        if (endDate != null) {
            dtYear = endDate.getYear();
            baseLabel = "采集截止 " + endDate;
        } else if (source.getAdDataYear() != null) {
            dtYear = source.getAdDataYear();
            baseLabel = "排放源 ad_data_year=" + dtYear;
        } else {
            r.evidence = "驱动字段 collection_record_end_date 与 ad_data_year 均缺失，无法计算 Δt，转人工必填";
            return r;
        }
        int dt = calcYear - dtYear;
        JsonNode entries = readTree(rule.getEntries());
        if (entries == null) {
            r.evidence = "规则库 A5 band 条目缺失";
            return r;
        }
        for (JsonNode band : entries) {
            if (band.size() < 3) continue;
            double lo = band.get(0).asDouble();
            double hi = band.get(1).asDouble();
            if (dt >= lo && dt < hi) {
                r.suggested = band.get(2).intValue();
                r.evidence = baseLabel + "，核算年度 " + calcYear
                        + "，Δt=" + dt + "，命中 band [" + lo + ", " + hi + ") → " + r.suggested + " 分";
                return r;
            }
        }
        r.evidence = "Δt = " + dt + " 年 不在 A5 band 定义域内，转人工必填";
        return r;
    }

    /**
     * mapping 规则求值：含 default_with_flag（A4 留空默认填充）与
     * neutral（A2 calib_not_applicable 中性分）两条缺失/不适用例外
     */
    private DimResult evalMapping(String dimCode, UncertaintyDimensionRule rule, String value) {
        DimResult r = new DimResult(dimCode);
        String driver = rule.getDriver();
        // 例外一：ad_geo_basis 留空 → 按 default_value（direct_metered）填充并标注
        if ((value == null || value.isBlank()) && "default_with_flag".equals(rule.getNullPolicy())
                && rule.getDefaultValue() != null) {
            value = rule.getDefaultValue();
            r.defaultFilled = true;
        }
        if (value == null || value.isBlank()) {
            r.evidence = "驱动字段 " + driver + " 缺失，转人工必填（禁止默认分填充）";
            return r;
        }
        // 例外二：命中 neutral_when_value（calib_not_applicable）→ 中性分
        if ("neutral".equals(rule.getNullPolicy()) && rule.getNeutralWhenValue() != null
                && rule.getNeutralWhenValue().equals(value) && rule.getNeutralScore() != null) {
            r.suggested = rule.getNeutralScore();
            r.evidence = driver + "=" + value + "，该维度不适用，取中性" + rule.getNeutralScore()
                    + "分，质量判断由 A1 承接";
            return r;
        }
        JsonNode entries = readTree(rule.getEntries());
        JsonNode scoreNode = entries == null ? null : entries.get(value);
        if (scoreNode == null || !scoreNode.isNumber()) {
            r.evidence = "驱动字段 " + driver + " 取值 " + value + " 不在规则库定义域，转人工必填";
            return r;
        }
        r.suggested = scoreNode.intValue();
        r.evidence = driver + "=" + value + "，命中 mapping 分值 " + r.suggested
                + (r.defaultFilled ? "（" + driver + " 留空，按 " + rule.getDefaultValue() + " 默认填充）" : "");
        return r;
    }

    /**
     * band 规则求值（A5/E4）：Δt = calcYear − dataYear，越域（含 Δt&lt;0）
     * → suggested=null 并触发 out_of_range_warning
     */
    private DimResult evalBand(String dimCode, UncertaintyDimensionRule rule, Integer dataYear, int calcYear,
                               String yearField) {
        DimResult r = new DimResult(dimCode);
        if (dataYear == null) {
            r.evidence = "驱动字段 " + yearField + " 缺失，无法计算 Δt，转人工必填";
            return r;
        }
        int dt = calcYear - dataYear;
        JsonNode entries = readTree(rule.getEntries());
        // 解析有效域：valid_range 缺省时按 entries 最小下界与最大上界推定
        double rangeLo = Double.NEGATIVE_INFINITY;
        double rangeHi = Double.POSITIVE_INFINITY;
        JsonNode validRange = readTree(rule.getValidRange());
        if (validRange != null && validRange.isArray() && validRange.size() == 2) {
            rangeLo = validRange.get(0).asDouble();
            rangeHi = validRange.get(1).asDouble();
        } else if (entries != null && entries.isArray() && !entries.isEmpty()) {
            rangeLo = entries.get(0).get(0).asDouble();
            rangeHi = entries.get(entries.size() - 1).get(1).asDouble();
        }
        if (dt < rangeLo || dt > rangeHi) {
            String warn = rule.getOutOfRangeWarning() != null ? rule.getOutOfRangeWarning()
                    : "Δt 越出有效域，转人工核实";
            r.warningTexts.add(warn);
            r.evidence = yearField + "=" + dataYear + "，Δt=" + dt + " 越出有效域 ["
                    + formatNum(rangeLo) + "," + formatNum(rangeHi) + "]，转人工必填";
            return r;
        }
        if (entries != null) {
            for (JsonNode band : entries) {
                double lo = band.get(0).asDouble();
                double hi = band.get(1).asDouble();
                if (dt >= lo && dt < hi) {
                    r.suggested = band.get(2).intValue();
                    r.evidence = yearField + "=" + dataYear + "，Δt=" + dt + "，命中分段 ["
                            + formatNum(lo) + "," + formatNum(hi) + ")，分值 " + r.suggested;
                    return r;
                }
            }
        }
        r.evidence = yearField + "=" + dataYear + "，Δt=" + dt + " 未命中任何分段，转人工必填";
        return r;
    }

    /**
     * A6 特殊处理（规范 5.8.1 第 3 步）：excluded 类（纯估算、无计量周期）
     * 自动中性 3 分并标注 neutral_excluded；否则按 ad_data_collection_quality 直接评分
     */
    private DimResult evalA6(UncertaintySourceMeta source) {
        DimResult r = new DimResult("A6");
        String tier = source.getAdMeteringTier();
        if (tier != null && A6_EXCLUDED_TIERS.contains(tier)) {
            r.suggested = 3;
            r.a6Source = "neutral_excluded";
            r.scoreSourcePreview = "auto_neutral_excluded";
            r.evidence = "ad_metering_tier=" + tier + "，纯估算无计量周期，中性3分（不归因于企业端采集质量）";
            return r;
        }
        Integer q = source.getAdDataCollectionQuality();
        r.a6Source = "normal";
        if (q == null || q < 1 || q > 5) {
            r.evidence = "驱动字段 ad_data_collection_quality "
                    + (q == null ? "缺失" : "取值 " + q + " 越出 1-5 定义域") + "，转人工必填";
            return r;
        }
        r.suggested = q;
        r.evidence = "ad_data_collection_quality=" + q + "，record 类按驱动字段直接评分";
        return r;
    }

    /**
     * 软校验（规范 5.8.4，追加警告不阻断）：
     * AD 组 W1/W2/W3/W9；EF 组 W10/W11/W13
     */
    private void applySoftWarnings(UncertaintySourceMeta source, String paramType, List<DimResult> results,
                                   Map<String, UncertaintyScore> existingRows, boolean w13Hit) {
        Map<String, DimResult> byDim = results.stream()
                .collect(Collectors.toMap(r -> r.dimCode, Function.identity()));
        if ("AD".equals(paramType)) {
            String tier = source.getAdMeteringTier();
            String calib = source.getAdMeterCalibration();
            String geo = source.getAdGeoBasis();
            if ("default_or_estimated".equals(tier) && calib != null && !"calib_not_applicable".equals(calib)) {
                byDim.get("A1").warningTexts.add(W1_TEXT);
            }
            if ("online_meter".equals(tier) && "calib_not_applicable".equals(calib)) {
                byDim.get("A2").warningTexts.add(W2_TEXT);
            }
            if (("literature_thirdparty".equals(tier) || "default_or_estimated".equals(tier))
                    && "direct_metered".equals(geo)) {
                byDim.get("A4").warningTexts.add(W3_TEXT);
            }
            Integer a1 = finalOrSuggested(existingRows, paramType, "A1", byDim.get("A1").suggested);
            Integer a2 = finalOrSuggested(existingRows, paramType, "A2", byDim.get("A2").suggested);
            if (a1 != null && a1 <= 2 && a2 != null && a2 == 5) {
                byDim.get("A1").warningTexts.add(W9_TEXT);
                byDim.get("A2").warningTexts.add(W9_TEXT);
            }
        } else {
            Integer e1 = finalOrSuggested(existingRows, paramType, "E1", byDim.get("E1").suggested);
            if ("general_or_estimated".equals(source.getEfSourceAuthority()) && e1 != null && e1 >= 4) {
                byDim.get("E1").warningTexts.add(W10_TEXT);
            }
            Integer e5 = finalOrSuggested(existingRows, paramType, "E5", byDim.get("E5").suggested);
            if ("generic_default".equals(source.getEfTechApplicability()) && e5 != null && e5 >= 4) {
                byDim.get("E5").warningTexts.add(W11_TEXT);
            }
            if (w13Hit) {
                results.forEach(r -> r.warningTexts.add(W13_TEXT));
            }
        }
    }

    /**
     * 取已有评分行的 final_score（无 final 时用本轮 suggested 判，W9/W10/W11）
     */
    private Integer finalOrSuggested(Map<String, UncertaintyScore> existingRows, String paramType, String dimCode,
                                     Integer suggested) {
        UncertaintyScore row = existingRows.get(paramType + "|" + dimCode);
        if (row != null && row.getFinalScore() != null) {
            return row.getFinalScore();
        }
        return suggested;
    }

    /**
     * 取 mapping 类型维度的驱动字段值
     */
    private String driverValue(UncertaintySourceMeta m, String paramType, String dimCode) {
        if ("AD".equals(paramType)) {
            return switch (dimCode) {
                case "A1" -> m.getAdMeteringTier();
                case "A2" -> m.getAdMeterCalibration();
                case "A4" -> m.getAdGeoBasis();
                default -> null;
            };
        }
        return switch (dimCode) {
            case "E1" -> m.getEfSourceAuthority();
            case "E2" -> m.getEfCompletenessScope();
            case "E3" -> m.getEfDataRegion();
            case "E5" -> m.getEfTechApplicability();
            case "E6" -> m.getEfConversionChain();
            default -> null;
        };
    }

    /**
     * SDQI 计算（规范 W12）：x=(Σw·s−Σw)/(5Σw−Σw)×100，
     * SDQI=min(5.0, 1.0+0.5×floor(x/12.5))，仅 weight&gt;0 且分值非空的维度参与
     *
     * @param useFinal true 用 final_score（无 final 回退 suggested），false 仅用 suggested_score
     * @return SDQI 分档值，无可参与维度时返回 NaN
     */
    private double computeSdqi(List<UncertaintyScore> rows, boolean useFinal) {
        double sumW = 0;
        double sumWS = 0;
        for (UncertaintyScore row : rows) {
            if (row.getWeight() == null || row.getWeight().signum() <= 0) {
                continue;
            }
            Integer s = useFinal
                    ? (row.getFinalScore() != null ? row.getFinalScore() : row.getSuggestedScore())
                    : row.getSuggestedScore();
            if (s == null) {
                continue;
            }
            double w = row.getWeight().doubleValue();
            sumW += w;
            sumWS += w * s;
        }
        if (sumW <= 0) {
            return Double.NaN;
        }
        double x = (sumWS - sumW) / (5 * sumW - sumW) * 100;
        return Math.min(5.0, 1.0 + 0.5 * Math.floor(x / 12.5));
    }

    /**
     * 向评分行 warnings 追加警告（逗号分隔，去重）
     */
    private void appendRowWarning(UncertaintyScore row, String warning) {
        if (row.getWarnings() == null || row.getWarnings().isBlank()) {
            row.setWarnings(warning);
        } else if (!row.getWarnings().contains(warning)) {
            row.setWarnings(row.getWarnings() + "," + warning);
        }
    }

    /**
     * 核算年度推定：calcYear 为空时取核算任务周期结束日期年份，
     * 结束日期缺失时回退起始日期年份，均缺失则报错要求显式传入
     */
    private int resolveCalcYear(CalculationTemplate template, Integer calcYear) {
        if (calcYear != null) {
            return calcYear;
        }
        if (template.getCalculationCycleEndDate() != null) {
            return template.getCalculationCycleEndDate().getYear();
        }
        if (template.getCalculationCycleStartDate() != null) {
            return template.getCalculationCycleStartDate().getYear();
        }
        throw new IllegalArgumentException("核算任务 " + template.getId()
                + " 缺少核算周期日期，无法推定核算年度，请显式传入 calcYear");
    }

    /**
     * 格式化数值（整数去小数点）
     */
    private String formatNum(double v) {
        return v == Math.rint(v) ? String.valueOf((long) v) : String.valueOf(v);
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
            throw new IllegalStateException("JSON 列反序列化失败：" + e.getMessage(), e);
        }
    }

    /**
     * 单维度评分中间结果
     */
    private static final class DimResult {
        /**
         * 维度编号
         */
        private final String dimCode;
        /**
         * 建议分（缺失/越域/不在定义域 → null）
         */
        private Integer suggested;
        /**
         * 判定依据
         */
        private String evidence;
        /**
         * A6 来源标记：normal / neutral_excluded
         */
        private String a6Source;
        /**
         * A6 excluded 类预览分值来源：auto_neutral_excluded
         */
        private String scoreSourcePreview;
        /**
         * ad_geo_basis 留空被默认填充标记
         */
        private boolean defaultFilled;
        /**
         * 该维度触发的警告文本列表
         */
        private final List<String> warningTexts = new ArrayList<>();

        private DimResult(String dimCode) {
            this.dimCode = dimCode;
        }
    }
}
