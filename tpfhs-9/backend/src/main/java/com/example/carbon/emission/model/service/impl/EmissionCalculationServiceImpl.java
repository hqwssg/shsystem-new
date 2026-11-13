package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.service.EmissionCalculationService;
import com.example.carbon.emission.model.support.DqiScoring;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 碳排放核算服务实现
 *
 * 完整核算流程：
 * <ol>
 *   <li>Step1：创建核算任务记录（CalculationTemplate），解析 taskConfig 确定核算周期</li>
 *   <li>Step2：遍历模版节点，创建核算节点快照（CalculationNode）</li>
 *   <li>Step3：仅对采集节点（typeId=3）计算能耗计量值并生成 CalculationNodeData（写入 emission_collection_node_data 表）。
 *       本步骤所有操作只针对采集节点进行，emission_collection_node_data 表只保存采集节点核算统计的数据。</li>
 *   <li>Step4：所有采集点核算完成后，统一对核算节点（typeId=2）和根节点（typeId=1）进行逐级汇总，
 *       按能源场景与排放小类保存直接值、子树小计及实际因子。</li>
 *   <li>Step5：完成核算，更新任务状态为成功（2）或失败（3）</li>
 * </ol>
 *
 * 当前进度：emission_collection_node_data 表记录采集节点（typeId=3）的核算结果，
 * emission_calc_node_summary 表记录核算节点与根节点的逐级汇总。任一节点计算失败不中断整体核算；整体异常则置 status=3。
 */
@Service
public class EmissionCalculationServiceImpl implements EmissionCalculationService {

    private static final Logger logger = LoggerFactory.getLogger(EmissionCalculationServiceImpl.class);

    /** 碳排放结果保留9位小数，支持万Nm³等小量级换算。 */
    private static final int SCALE = 9;

    /** 节点类型ID：根节点 */
    private static final int TYPE_ID_ROOT = 1;
    /** 节点类型ID：核算子节点 */
    private static final int TYPE_ID_CALCULATION = 2;
    /** 节点类型ID：采集节点 */
    private static final int TYPE_ID_COLLECTION = 3;
    /** 节点类型ID：运输节点 */
    private static final int TYPE_ID_TRANSPORT = 4;

    /** 错误码：Step4 逐级汇总失败 */
    private static final int ERROR_CODE_STEP4 = 2;

    /** 采集点类型：1-电力表，2-化石燃料，3-外购热能 */
    private static final int COLLECTION_TYPE_ELECTRICITY = 1;
    private static final int COLLECTION_TYPE_FOSSIL = 2;
    private static final int COLLECTION_TYPE_HEAT = 3;

    /** 核算任务状态 */
    private static final int TEMPLATE_STATUS_RUNNING = 1;
    private static final int TEMPLATE_STATUS_SUCCESS = 2;
    private static final int TEMPLATE_STATUS_FAILED = 3;

    @Autowired
    private EmissionNodeRepository emissionNodeRepository;
    @Autowired
    private EmissionNodeConfigRepository emissionNodeConfigRepository;
    @Autowired
    private EmissionNodeInfoRepository emissionNodeInfoRepository;
    @Autowired
    private MeterInfoRepository meterInfoRepository;
    @Autowired
    private FossilFuelMeterInfoRepository fossilFuelMeterInfoRepository;
    @Autowired
    private PurchasedHeatMeterInfoRepository purchasedHeatMeterInfoRepository;
    @Autowired
    private CalculationTemplateRepository calculationTemplateRepository;
    @Autowired
    private CalculationNodeRepository calculationNodeRepository;
    @Autowired
    private CalculationNodeDataRepository calculationNodeDataRepository;
    @Autowired
    private TemplateRepository templateRepository;
    @Autowired
    private EnergyMeasurementCalculator energyMeasurementCalculator;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private FactorDimensionService factorDimensionService;
    @Autowired
    private EffectiveFactorResolver effectiveFactorResolver;

    @Autowired
    private TaskScheduleConfigService taskScheduleConfigService;

    @Autowired
    private com.example.carbon.emission.model.service.EmissionDataFreshnessService dataFreshnessService;

    @Autowired
    private CalculationTaskReservationService taskReservationService;

    @Autowired
    private NodeInclusionResolver nodeInclusionResolver;

    @Autowired
    private ManualCalculationDataGuard manualCalculationDataGuard;

    @Autowired
    private TemplateCollectionPointUniquenessGuard collectionPointUniquenessGuard;

    @Autowired
    private MonthlyPublicationCoordinator monthlyPublicationCoordinator;

    /**
     * 核算节点逐级汇总处理器。
     * 仅在 "job" profile 下存在 Bean；非 job profile（纯 web）时为 null，
     * 使用时需判空并记录 WARN 日志。
     */
    @Autowired(required = false)
    private CalcNodeSummaryProcessor calcNodeSummaryProcessor;

    @Override
    public void executeEmissionCalculation(Long templateId) {
        executeEmissionCalculation(templateId, null, null, 0L, null, true);
    }

    @Override
    public CalculationTemplate executeEmissionCalculation(Long templateId, LocalDate requestedStartDate,
                                                          LocalDate requestedEndDate, Long initiatorId,
                                                          String initiatorName) {
        return executeEmissionCalculation(templateId, requestedStartDate, requestedEndDate,
                initiatorId, initiatorName, true);
    }

    @Override
    public CalculationTemplate executeEmissionCalculation(Long templateId, LocalDate requestedStartDate,
                                                          LocalDate requestedEndDate, Long initiatorId,
                                                          String initiatorName,
                                                          boolean generateMonthlyRecords) {
        logger.info("***开始执行碳排放核算，模版ID: {}", templateId);

        // Step 1：创建核算任务记录
        Template template = templateRepository.findById(templateId).orElse(null);
        if (template == null) {
            logger.error("***模版不存在，模版ID: {}", templateId);
            return null;
        }
        collectionPointUniquenessGuard.requireUnique(templateId);

        LocalDate cycleStartDate;
        LocalDate cycleEndDate;
        if (requestedStartDate != null || requestedEndDate != null) {
            if (requestedStartDate == null || requestedEndDate == null || requestedStartDate.isAfter(requestedEndDate)) {
                throw new IllegalArgumentException("手动核算周期非法");
            }
            cycleStartDate = requestedStartDate;
            cycleEndDate = requestedEndDate;
        } else {
            LocalDate[] cycle = taskScheduleConfigService.calculateCycle(template.getTaskConfig(), LocalDate.now());
            cycleStartDate = cycle[0];
            cycleEndDate = cycle[1];
        }
        logger.info("***核算周期: {} ~ {}, 模版ID: {}", cycleStartDate, cycleEndDate, templateId);

        final CalculationTemplate calcTemplate;
        final long dataRevision = dataFreshnessService.currentRevision(templateId);
        try {
            calcTemplate = taskReservationService.reserve(templateId, cycleStartDate, cycleEndDate, dataRevision,
                    initiatorId != null && initiatorId > 0 ? 2 : 1, initiatorId, initiatorName);
        } catch (DataIntegrityViolationException duplicate) {
            logger.info("***同一模版周期已有核算任务，跳过重复执行，模版ID: {}, 周期: {}~{}",
                    templateId, cycleStartDate, cycleEndDate);
            CalculationTemplate existing = calculationTemplateRepository
                    .findFirstByTemplateIdAndCalculationCycleStartDateAndCalculationCycleEndDateAndDataRevisionOrderByIdDesc(
                            templateId, cycleStartDate, cycleEndDate, dataRevision)
                    .orElse(null);
            if (existing != null) {
                existing.setReusedExistingResult(true);
                existing.setMonthlyRecordStatus("SKIPPED_REUSED");
                existing.setMonthlyRecordMessage("复用已有核算结果，本次未重新生成月度记录");
            }
            return existing;
        }

        try {
            long capturedRevision = dataFreshnessService.captureCalculation(calcTemplate.getId(), templateId);
            // Step 2：先完整创建快照，再把设计态父节点转换为父快照ID。
            // emission_node.parent_id 与 emission_calculation_node.parent_id 的语义不同，不能直接复制。
            List<EmissionNode> nodes = emissionNodeRepository.findByTemplateId(templateId);
            logger.info("***模版下节点数: {}, 模版ID: {}", nodes.size(), templateId);
            Map<Long, NodeInclusionResolver.InclusionDecision> inclusionDecisions =
                    nodeInclusionResolver.resolve(nodes);
            Map<Long, CalculationNode> snapshotBySourceId = new HashMap<>();
            for (EmissionNode node : nodes) {
                CalculationNode calcNode = new CalculationNode();
                calcNode.setCalculationTemplateId(calcTemplate.getId());
                calcNode.setNodeId(node.getId());
                calcNode.setName(node.getName());
                calcNode.setTypeId(node.getTypeId());
                calcNode.setParentId(null);
                NodeInclusionResolver.InclusionDecision inclusion = inclusionDecisions.get(node.getId());
                calcNode.setIncludeInCalculation(inclusion == null || inclusion.included());
                calcNode.setExcludedByNodeId(inclusion == null ? null : inclusion.excludedByNodeId());

                // 核算子节点（typeId=2）查询 nodeCategory
                if (node.getTypeId() != null && node.getTypeId() == TYPE_ID_CALCULATION) {
                    emissionNodeInfoRepository.findByNodeId(node.getId())
                            .ifPresent(info -> calcNode.setNodeCategory(info.getNodeCategory()));
                }
                CalculationNode saved = calculationNodeRepository.save(calcNode);
                if (snapshotBySourceId.putIfAbsent(node.getId(), saved) != null) {
                    throw new IllegalStateException("同一模版存在重复源节点，nodeId=" + node.getId());
                }
            }

            for (EmissionNode node : nodes) {
                Long parentSourceId = node.getParentId();
                if (parentSourceId == null) {
                    continue;
                }
                CalculationNode snapshot = snapshotBySourceId.get(node.getId());
                CalculationNode parentSnapshot = snapshotBySourceId.get(parentSourceId);
                if (snapshot == null || parentSnapshot == null) {
                    throw new IllegalStateException("创建核算快照失败：找不到父源节点，sourceNodeId="
                            + node.getId() + ", parentSourceId=" + parentSourceId);
                }
                snapshot.setParentId(parentSnapshot.getId());
            }
            calculationNodeRepository.saveAll(new ArrayList<>(snapshotBySourceId.values()));

            Long factorTemplateId = template.getFactorTemplateId();
            // Step 3：完整快照树保存后，再处理采集节点。
            for (EmissionNode node : nodes) {
                if (node.getTypeId() != null && node.getTypeId() == TYPE_ID_COLLECTION) {
                    CalculationNode calcNode = snapshotBySourceId.get(node.getId());
                    if (Boolean.FALSE.equals(calcNode.getIncludeInCalculation())) {
                        logger.info("***采集节点因不纳入核算规则跳过，节点ID: {}, 排除来源节点ID: {}",
                                node.getId(), calcNode.getExcludedByNodeId());
                        continue;
                    }
                    try {
                        processCollectionNode(calcNode.getId(), node.getId(), factorTemplateId,
                                cycleStartDate, cycleEndDate);
                    } catch (DuplicateCollectionPeriodException e) {
                        saveErrorNodeData(calcNode.getId(), node.getId(), e.getMessage());
                        calcTemplate.setErrorCode(EmissionCalculationService.ERROR_CODE_DUPLICATE_COLLECTION_PERIOD);
                        calcTemplate.setFailureMessage(e.getMessage());
                        logger.error("***采集点计费周期重复，节点ID: {}, 模版ID: {}", node.getId(), templateId, e);
                        throw e;
                    } catch (IllegalStateException e) {
                        // 因子值、单位或换算路径不完整属于核算口径错误，必须使任务失败，
                        // 不能生成部分成功且量纲不可信的结果。
                        logger.error("***节点因子量纲核算失败，节点ID: {}, 模版ID: {}",
                                node.getId(), templateId, e);
                        throw e;
                    } catch (Exception e) {
                        logger.error("***节点核算失败，节点ID: {}, 模版ID: {}", node.getId(), templateId, e);
                        // 不能吞掉未预期异常后继续生成成功的全零汇总。保留节点占位数据，
                        // 由统一异常分支将任务标记为失败并返回可定位的原因。
                        saveErrorNodeData(calcNode.getId(), node.getId(),
                                "采集点核算失败: " + safeMessage(e));
                        calcTemplate.setErrorCode(1);
                        calcTemplate.setFailureMessage("采集点 " + node.getId() + " 核算失败: " + safeMessage(e));
                        throw new IllegalStateException(calcTemplate.getFailureMessage(), e);
                    }
                }
            }

            // 所有采集点（typeId=3）统计核算完成后，在此统一对核算节点（typeId=2）
            // 和根节点（typeId=1）进行操作（汇总下级节点能耗、按因子折算等）。

            // 没有任何有效采集数据时返回可解释的 422，避免把全零结果标记为成功。
            // 不完整但确有读数的结果允许继续保留缺口。
            if (manualCalculationDataGuard.hasNoValidIncludedData(calcTemplate)) {
                calcTemplate.setErrorCode(EmissionCalculationService.ERROR_CODE_NO_VALID_DATA);
                throw new IllegalStateException("无有效核算数据：所选周期内没有已审核且状态正常的采集记录");
            }

            // Step 4：核算节点与根节点逐级汇总（自底向上）
            try {
                logger.info("[Step4] 开始逐级汇总核算节点，模版ID: {}, 核算ID: {}",
                        templateId, calcTemplate.getId());
                if (calcNodeSummaryProcessor == null) {
                    logger.warn("[Step4] CalcNodeSummaryProcessor Bean 未启用，非job profile，跳过。");
                    throw new IllegalStateException("核算汇总组件未启用，请使用包含 job profile 的后端配置");
                } else {
                    int summaryRows = calcNodeSummaryProcessor.process(calcTemplate.getId());
                    if (hasSummarizableCollectionData(calcTemplate.getId()) && summaryRows == 0) {
                        calcTemplate.setErrorCode(ERROR_CODE_STEP4);
                        throw new IllegalStateException("存在有效采集节点数据，但未生成任何汇总结果");
                    }
                    logger.info("[Step4] 逐级汇总完成，模版ID: {}, 核算ID: {}",
                            templateId, calcTemplate.getId());
                }
            } catch (Exception e) {
                logger.error("[Step4] 失败，模版ID: {}, 核算ID: {}", templateId, calcTemplate.getId(), e);
                calcTemplate.setErrorCode(ERROR_CODE_STEP4);
                // 直接抛到外层异常分支，由外层统一置 status=FAILED
                throw new RuntimeException("核算节点逐级汇总失败", e);
            }

            // Step 5：完成核算
            calcTemplate.setStatus(TEMPLATE_STATUS_SUCCESS);
            calcTemplate.setCalculationEndTime(LocalDateTime.now());
            // 月度发布只能在成功状态已经写入数据库并完成提交边界后启动。
            // 本服务本身不持有外层事务，saveAndFlush 返回时 Spring Data 写事务已完成。
            calculationTemplateRepository.saveAndFlush(calcTemplate);
            dataFreshnessService.completeCalculation(calcTemplate.getId(), templateId, capturedRevision);
            logger.info("***碳排放核算完成，模版ID: {}, 核算ID: {}", templateId, calcTemplate.getId());

            monthlyPublicationCoordinator.publishSafely(calcTemplate, template, generateMonthlyRecords);

        } catch (Exception e) {
            logger.error("***碳排放核算失败，模版ID: {}, 核算ID: {}", templateId, calcTemplate.getId(), e);
            calcTemplate.setStatus(TEMPLATE_STATUS_FAILED);
            if (calcTemplate.getErrorCode() == null || calcTemplate.getErrorCode() == 0) {
                calcTemplate.setErrorCode(1);
            }
            if (calcTemplate.getFailureMessage() == null || calcTemplate.getFailureMessage().isBlank()) {
                calcTemplate.setFailureMessage(e.getMessage());
            }
            calcTemplate.setCalculationEndTime(LocalDateTime.now());
            calculationTemplateRepository.save(calcTemplate);
        }
        return calcTemplate;
    }

    /**
     * 处理单个采集节点：查询配置和采集点信息，调用计算器，保存 CalculationNodeData。
     * <p>
     * 因子回退机制：采集点因子优先使用节点配置（emission_node_config.carbon_emission_factor），
     * 为空时回退到因子模版缺省因子（emission_default_factor 表中 factor_template_id
     * + subcategory_code/name 匹配且 status=1 的记录）。
     * 即"采集点因子优先使用节点配置，为空时回退到因子模版缺省因子"。
     *
     * @param calcNodeId      核算主表ID（calculation_node 主键）
     * @param nodeId          采集节点配置ID（emission_node_config 主键）
     * @param factorTemplateId 当前核算模版关联的因子模版ID（用于查模版缺省因子）
     * @param cycleStartDate  核算周期开始日期
     * @param cycleEndDate    核算周期结束日期
     */
    private void processCollectionNode(Long calcNodeId, Long nodeId, Long factorTemplateId,
                                       LocalDate cycleStartDate, LocalDate cycleEndDate) {
        EmissionNodeConfig config = emissionNodeConfigRepository.findByNodeId(nodeId).orElse(null);
        if (config == null) {
            logger.warn("***节点配置不存在，节点ID: {}", nodeId);
            saveErrorNodeData(calcNodeId, nodeId, "节点配置不存在");
            return;
        }

        Integer collectionPointType = config.getCollectionPointType();
        Long collectionPointId = config.getCollectionPointId();
        if (collectionPointType == null || collectionPointId == null) {
            logger.warn("***采集点信息不完整，节点ID: {}", nodeId);
            saveErrorNodeData(calcNodeId, config, "采集点信息不完整");
            return;
        }

        // 获取采集点信息
        CollectionPointInfo cpInfo = getCollectionPointInfo(collectionPointType, collectionPointId);
        if (cpInfo == null) {
            logger.warn("***采集点不存在，类型: {}, ID: {}", collectionPointType, collectionPointId);
            saveErrorNodeData(calcNodeId, config, "采集点不存在");
            return;
        }

        // 调用能耗计量值计算器
        EnergyMeasurementCalculator.Result calcResult = energyMeasurementCalculator.calculate(
                collectionPointType, collectionPointId, cpInfo.isCumulative,
                cycleStartDate, cycleEndDate);

        // 创建 CalculationNodeData
        CalculationNodeData data = new CalculationNodeData();
        data.setCalculationNodeId(calcNodeId);
        data.setCollectionPointType(collectionPointType);
        data.setCollectionPointId(collectionPointId);
        data.setEmissionCategory(config.getEmissionCategory());
        data.setCarbonEmissionFactor(config.getCarbonEmissionFactor());

        // 采集点字段
        data.setEmissionSubcategory(cpInfo.emissionSubcategory);
        data.setIsCumulative(cpInfo.isCumulative);
        data.setIsMobileSource(cpInfo.isMobileSource);
        data.setMeasurementUnit(cpInfo.measurementUnit);
        data.setEnergyCategoryL1(cpInfo.energyCategoryL1);
        data.setEnergyCategoryL2(cpInfo.energyCategoryL2);
        data.setEnergyCategoryL3(cpInfo.energyCategoryL3);
        data.setEnergyUseCategory(cpInfo.energyUseCategory);
        data.setDqiA1Score(cpInfo.dqiA1Score);
        data.setDqiA2Score(cpInfo.dqiA2Score);
        data.setDqiA4Score(cpInfo.dqiA4Score);

        // 计算结果
        data.setEnergyMeasurementValue(calcResult.getEnergyMeasurementValue());
        data.setDataStatus(calcResult.getDataStatus());
        data.setCollectionRecordStartDate(calcResult.getCollectionRecordStartDate());
        data.setCollectionRecordEndDate(calcResult.getCollectionRecordEndDate());
        data.setDataMissingDescription(calcResult.getDataMissingDescription());
        data.setAdjustedEnergyValue(calcResult.getAdjustedEnergyValue());
        data.setRolloverApplied(calcResult.getRolloverApplied());
        data.setRolloverThreshold(calcResult.getRolloverThreshold());
        boolean adjusted = calcResult.getAdjustedEnergyValue() != null
                && calcResult.getEnergyMeasurementValue() != null
                && calcResult.getAdjustedEnergyValue().compareTo(calcResult.getEnergyMeasurementValue()) != 0;
        data.setDqiA6Score(DqiScoring.a6(calcResult.getDataStatus(),
                calcResult.getDataMissingDescription(), adjusted,
                Integer.valueOf(0).equals(cpInfo.isCumulative) && calcResult.getDataStatus() != null
                        && calcResult.getDataStatus() == 1));

        // 碳排放量 = 换算到因子分母单位后的活动量 × 碳排放因子，
        // 再将因子分子质量单位统一为 tCO2e。
        EffectiveFactorResolver.FactorSnapshot factorSnapshot = effectiveFactorResolver.resolve(
                config, factorTemplateId, cpInfo.emissionSubcategory);
        BigDecimal factor = factorSnapshot.value();
        String factorUnit = factorSnapshot.unit();
        logger.info("节点采用{}因子：节点ID={}，小类={}，因子值={}，单位={}",
                factorSnapshot.source(), nodeId, cpInfo.emissionSubcategory, factor, factorUnit);

        FactorDimensionService.CarbonResult rawCarbon = factorDimensionService.calculate(
                cpInfo.emissionSubcategory, calcResult.getEnergyMeasurementValue(),
                cpInfo.measurementUnit, factor, factorUnit);
        FactorDimensionService.CarbonResult adjustedCarbon = factorDimensionService.calculate(
                cpInfo.emissionSubcategory, calcResult.getAdjustedEnergyValue(),
                cpInfo.measurementUnit, factor, factorUnit);
        data.setCarbonEmissionFactor(factor);
        // 核算明细保存本次实际选中的完整因子快照；规范换算单位只参与计算，
        // 不得用其覆盖模板或节点快照中的原始单位文本。
        data.setCarbonEmissionFactorUnit(factorUnit);
        data.setCarbonEmissionUnit(FactorDimensionService.CARBON_RESULT_UNIT);
        data.setCarbonEmission(rawCarbon.carbonTco2e().setScale(SCALE, RoundingMode.HALF_UP));
        data.setAdjustedCarbonEmission(adjustedCarbon.carbonTco2e().setScale(SCALE, RoundingMode.HALF_UP));
        EffectiveFactorResolver.FactorDqiSnapshot factorDqi = factorSnapshot.dqi();
        if (factorDqi != null) {
            data.setDqiE1Score(factorDqi.e1());
            data.setDqiE2Score(factorDqi.e2());
            data.setDqiE3Score(factorDqi.e3());
            data.setDqiE4Score(DqiScoring.e4(factorDqi.fixedE4(), factorDqi.factorYear(), cycleStartDate));
            data.setDqiE5Score(factorDqi.e5());
            data.setDqiE6Score(factorDqi.e6());
        }

        calculationNodeDataRepository.save(data);
        logger.debug("***节点核算完成，节点ID: {}, 数据状态: {}", nodeId, calcResult.getDataStatus());
    }

    private String trimToNull(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }

    private String safeMessage(Throwable error) {
        if (error == null) {
            return "未知错误";
        }
        String message = error.getMessage();
        return message == null || message.isBlank() ? error.getClass().getSimpleName() : message;
    }

    /**
     * 只有本次存在完整采集数据时，才要求 Step4 至少生成一条汇总结果。
     * 无数据或不完整数据仍可按既有规则结束，不把合法空场景误判为汇总故障。
     */
    private boolean hasSummarizableCollectionData(Long calcTemplateId) {
        List<CalculationNode> collectionNodes = calculationNodeRepository
                .findByCalculationTemplateId(calcTemplateId).stream()
                .filter(node -> node.getTypeId() != null && node.getTypeId() == TYPE_ID_COLLECTION)
                .toList();
        if (collectionNodes.isEmpty()) {
            return false;
        }
        List<Long> ids = collectionNodes.stream().map(CalculationNode::getId).toList();
        return calculationNodeDataRepository.findByCalculationNodeIdIn(ids).stream()
                .anyMatch(data -> data.getDataStatus() != null && data.getDataStatus() == 1);
    }

    /**
     * 根据采集点类型查询对应采集点表，提取计算所需字段
     */
    private CollectionPointInfo getCollectionPointInfo(Integer collectionPointType, Long collectionPointId) {
        CollectionPointInfo info = new CollectionPointInfo();
        switch (collectionPointType) {
            case COLLECTION_TYPE_ELECTRICITY:
                return meterInfoRepository.findById(collectionPointId).map(m -> {
                    info.isCumulative = m.getIsCumulative();
                    info.emissionSubcategory = m.getEmissionSubcategory();
                    info.isMobileSource = m.getIsMobileSource();
                    info.measurementUnit = m.getMeasurementUnit();
                    info.energyCategoryL1 = m.getEnergyCategoryL1();
                    info.energyCategoryL2 = m.getEnergyCategoryL2();
                    info.energyCategoryL3 = m.getEnergyCategoryL3();
                    info.energyUseCategory = m.getEnergyUseCategory();
                    copyActivityDqi(info, m);
                    return info;
                }).orElse(null);
            case COLLECTION_TYPE_FOSSIL:
                return fossilFuelMeterInfoRepository.findById(collectionPointId).map(m -> {
                    info.isCumulative = m.getIsCumulative();
                    info.emissionSubcategory = m.getFuelType();
                    info.isMobileSource = m.getIsMobileSource();
                    info.measurementUnit = m.getMeasurementUnit();
                    info.energyCategoryL1 = m.getEnergyCategoryL1();
                    info.energyCategoryL2 = m.getEnergyCategoryL2();
                    info.energyCategoryL3 = m.getEnergyCategoryL3();
                    info.energyUseCategory = m.getEnergyUseCategory();
                    copyActivityDqi(info, m);
                    return info;
                }).orElse(null);
            case COLLECTION_TYPE_HEAT:
                return purchasedHeatMeterInfoRepository.findById(collectionPointId).map(m -> {
                    info.isCumulative = m.getIsCumulative();
                    info.emissionSubcategory = m.getHeatType();
                    info.isMobileSource = m.getIsMobileSource();
                    info.measurementUnit = m.getMeasurementUnit();
                    info.energyCategoryL1 = m.getEnergyCategoryL1();
                    info.energyCategoryL2 = m.getEnergyCategoryL2();
                    info.energyCategoryL3 = m.getEnergyCategoryL3();
                    info.energyUseCategory = m.getEnergyUseCategory();
                    copyActivityDqi(info, m);
                    return info;
                }).orElse(null);
            default:
                return null;
        }
    }

    private void copyActivityDqi(CollectionPointInfo target,
                                 com.example.carbon.emission.model.support.ActivityDataDqi source) {
        target.dqiA1Score = source.getDqiA1Score();
        target.dqiA2Score = source.getDqiA2Score();
        target.dqiA4Score = source.getDqiA4Score();
    }

    /**
     * 保存节点核算失败的占位记录（无配置时）
     */
    private void saveErrorNodeData(Long calcNodeId, Long nodeId, String description) {
        CalculationNodeData data = new CalculationNodeData();
        data.setCalculationNodeId(calcNodeId);
        data.setDataStatus(2);
        data.setDataMissingDescription(description);
        data.setEnergyMeasurementValue(BigDecimal.ZERO.setScale(SCALE, RoundingMode.HALF_UP));
        data.setAdjustedEnergyValue(BigDecimal.ZERO.setScale(SCALE, RoundingMode.HALF_UP));
        calculationNodeDataRepository.save(data);
    }

    /**
     * 保存节点核算失败的占位记录（有配置但采集点异常时）
     */
    private void saveErrorNodeData(Long calcNodeId, EmissionNodeConfig config, String description) {
        CalculationNodeData data = new CalculationNodeData();
        data.setCalculationNodeId(calcNodeId);
        data.setCollectionPointType(config.getCollectionPointType());
        data.setCollectionPointId(config.getCollectionPointId());
        data.setEmissionCategory(config.getEmissionCategory());
        data.setCarbonEmissionFactor(config.getCarbonEmissionFactor());
        data.setDataStatus(2);
        data.setDataMissingDescription(description);
        data.setEnergyMeasurementValue(BigDecimal.ZERO.setScale(SCALE, RoundingMode.HALF_UP));
        data.setAdjustedEnergyValue(BigDecimal.ZERO.setScale(SCALE, RoundingMode.HALF_UP));
        calculationNodeDataRepository.save(data);
    }

    /**
     * 解析 taskConfig 确定核算周期起止日期
     *
     * 复用 EmissionScheduler 中的 taskConfig 解析逻辑（cycleType/delayDays），
     * 基于"延迟核算日期"后的日期推算上一个统计周期：
     * <ul>
     *   <li>DAILY：前一天</li>
     *   <li>WEEKLY：上一周（周一至周日）</li>
     *   <li>MONTHLY：上个月（1日至月末）</li>
     *   <li>QUARTERLY：上一季度</li>
     *   <li>YEARLY：上一年（1月1日至12月31日）</li>
     * </ul>
     * taskConfig 为空或解析失败时，默认按"上月1日到上月末日"。
     *
     * @param taskConfigJson taskConfig JSON 字符串
     * @return [核算周期起始日期, 核算周期截止日期]
     */
    private LocalDate[] parseCalculationCycle(String taskConfigJson) {
        LocalDate now = LocalDate.now();
        LocalDate defaultStart = now.minusMonths(1).withDayOfMonth(1);
        LocalDate defaultEnd = now.minusMonths(1).withDayOfMonth(now.minusMonths(1).lengthOfMonth());

        if (taskConfigJson == null || taskConfigJson.isEmpty()) {
            return new LocalDate[]{defaultStart, defaultEnd};
        }

        try {
            JsonNode taskConfig = objectMapper.readTree(taskConfigJson);
            String cycleType = getTextOrNull(taskConfig, "cycleType");
            int delayDays = taskConfig.has("delayDays") ? taskConfig.get("delayDays").asInt(0) : 0;
            if (delayDays < 0) {
                delayDays = 0;
            }
            LocalDate adjustedDate = now.minusDays(delayDays);

            if (cycleType == null) {
                return new LocalDate[]{defaultStart, defaultEnd};
            }

            switch (cycleType) {
                case "DAILY":
                    return new LocalDate[]{adjustedDate.minusDays(1), adjustedDate.minusDays(1)};
                case "WEEKLY": {
                    LocalDate monday = adjustedDate.with(DayOfWeek.MONDAY);
                    LocalDate prevMonday = monday.minusWeeks(1);
                    LocalDate prevSunday = prevMonday.plusDays(6);
                    return new LocalDate[]{prevMonday, prevSunday};
                }
                case "MONTHLY": {
                    LocalDate prevMonth = adjustedDate.minusMonths(1);
                    return new LocalDate[]{
                            prevMonth.withDayOfMonth(1),
                            prevMonth.withDayOfMonth(prevMonth.lengthOfMonth())
                    };
                }
                case "QUARTERLY": {
                    return computePreviousQuarter(adjustedDate);
                }
                case "YEARLY": {
                    int prevYear = adjustedDate.getYear() - 1;
                    return new LocalDate[]{
                            LocalDate.of(prevYear, 1, 1),
                            LocalDate.of(prevYear, 12, 31)
                    };
                }
                default:
                    return new LocalDate[]{defaultStart, defaultEnd};
            }
        } catch (Exception e) {
            logger.warn("***解析 taskConfig 失败，使用默认核算周期(上月): {}", e.getMessage());
            return new LocalDate[]{defaultStart, defaultEnd};
        }
    }

    /**
     * 计算上一季度的起止日期
     */
    private LocalDate[] computePreviousQuarter(LocalDate date) {
        int month = date.getMonthValue();
        int prevYear = date.getYear();
        int prevQuarterStartMonth;
        if (month >= 1 && month <= 3) {
            // 当前Q1，上一Q4属于去年
            prevQuarterStartMonth = 10;
            prevYear = date.getYear() - 1;
        } else if (month >= 4 && month <= 6) {
            prevQuarterStartMonth = 1;
        } else if (month >= 7 && month <= 9) {
            prevQuarterStartMonth = 4;
        } else {
            prevQuarterStartMonth = 7;
        }
        LocalDate qStart = LocalDate.of(prevYear, prevQuarterStartMonth, 1);
        LocalDate qEnd = qStart.plusMonths(2).withDayOfMonth(qStart.plusMonths(2).lengthOfMonth());
        return new LocalDate[]{qStart, qEnd};
    }

    /**
     * 安全获取 JSON 字段值（复用 EmissionScheduler 的同名逻辑）
     */
    private String getTextOrNull(JsonNode node, String fieldName) {
        JsonNode fieldNode = node.get(fieldName);
        if (fieldNode == null || fieldNode.isNull()) {
            return null;
        }
        String value = fieldNode.asText();
        if ("null".equals(value) || value.isEmpty()) {
            return null;
        }
        return value;
    }

    /**
     * 采集点信息持有者（统一三张采集点表的字段访问）
     */
    private static class CollectionPointInfo {
        Integer isCumulative;
        String emissionSubcategory;
        Integer isMobileSource;
        String measurementUnit;
        String energyCategoryL1;
        String energyCategoryL2;
        String energyCategoryL3;
        String energyUseCategory;
        Integer dqiA1Score;
        Integer dqiA2Score;
        Integer dqiA4Score;
    }
}
