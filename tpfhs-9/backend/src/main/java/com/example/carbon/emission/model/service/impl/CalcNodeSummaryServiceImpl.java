package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalcNodeSummary;
import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.dto.CalcNodeSummaryResponse;
import com.example.carbon.emission.model.repository.CalcNodeSummaryRepository;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.EnergyCategoryRepository;
import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EnergyCategory;
import com.example.carbon.emission.model.repository.CalculationNodeDataRepository;
import com.example.carbon.emission.model.entity.CalculationNodeData;
import com.example.carbon.emission.model.service.CalcNodeSummaryService;
import com.example.carbon.emission.model.service.DataDictService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import jakarta.persistence.criteria.Root;
import jakarta.persistence.criteria.Subquery;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

/**
 * 碳排放核算节点汇总 Service 实现
 */
@Service
@Transactional(readOnly = true)
public class CalcNodeSummaryServiceImpl implements CalcNodeSummaryService {

    private static final Logger log = LoggerFactory.getLogger(CalcNodeSummaryServiceImpl.class);

    /**
     * 核算节点汇总数据 Repository
     */
    @Autowired
    private CalcNodeSummaryRepository calcNodeSummaryRepository;

    /**
     * 核算任务模板 Repository，用于按日期范围筛选成功的核算任务
     */
    @Autowired
    private CalculationTemplateRepository calculationTemplateRepository;

    @Autowired
    private TemplateRepository templateRepository;

    @Autowired
    private EmissionNodeRepository emissionNodeRepository;

    @Autowired
    private EnergyCategoryRepository energyCategoryRepository;

    @Autowired
    private CalculationNodeDataRepository calculationNodeDataRepository;

    @Autowired
    private DataDictService dataDictService;

    @Override
    public List<CalcNodeSummary> queryByTemplate(Long templateId, Long nodeId, String subcategoryCode,
                                                 String l1, String l2, String l3) {
        if (templateId == null) {
            log.warn("queryByTemplate 调用失败：templateId 为 null");
            return Collections.emptyList();
        }

        // 步骤1：以 templateId 为主键拉取该核算任务的全部汇总记录
        List<CalcNodeSummary> all = calcNodeSummaryRepository.findByCalculationTemplateId(templateId);
        if (all == null || all.isEmpty()) {
            return Collections.emptyList();
        }

        // 步骤2：在 Service 层通过 Stream 做维度过滤；参数为 null 时不加入条件
        Stream<CalcNodeSummary> stream = all.stream();

        if (nodeId != null) {
            stream = stream.filter(s -> Objects.equals(nodeId, s.getCalculationNodeId()));
        }
        if (subcategoryCode != null && !subcategoryCode.isBlank()) {
            stream = stream.filter(s -> Objects.equals(subcategoryCode, s.getEmissionSubcategory()));
        }
        if (l1 != null && !l1.isBlank()) {
            stream = stream.filter(s -> Objects.equals(l1, s.getEnergyCategoryL1()));
        }
        if (l2 != null && !l2.isBlank()) {
            stream = stream.filter(s -> Objects.equals(l2, s.getEnergyCategoryL2()));
        }
        if (l3 != null && !l3.isBlank()) {
            stream = stream.filter(s -> Objects.equals(l3, s.getEnergyCategoryL3()));
        }

        return stream.collect(Collectors.toList());
    }

    @Override
    public List<CalcNodeSummary> queryBySourceNodeAndCycle(Long sourceNodeId, LocalDate start, LocalDate end) {
        if (sourceNodeId == null || start == null || end == null) {
            log.warn("queryBySourceNodeAndCycle 调用失败：存在必填参数为 null，sourceNodeId={}, start={}, end={}",
                    sourceNodeId, start, end);
            return Collections.emptyList();
        }

        // 步骤1：查询核算周期起始日期在 [start, end] 区间内且执行成功(status=2)的核算任务
        List<CalculationTemplate> templates = calculationTemplateRepository
                .findByCalculationCycleStartDateBetweenAndStatus(start, end, 2);

        if (templates == null || templates.isEmpty()) {
            log.debug("queryBySourceNodeAndCycle：日期范围内无成功的核算任务，start={}, end={}", start, end);
            return Collections.emptyList();
        }

        // 步骤2：提取模板ID集合
        List<Long> templateIds = templates.stream()
                .map(CalculationTemplate::getId)
                .collect(Collectors.toList());

        // 步骤3：批量查询这些模板下的汇总记录
        List<CalcNodeSummary> summaries = calcNodeSummaryRepository.findByCalculationTemplateIdIn(templateIds);
        if (summaries == null || summaries.isEmpty()) {
            return Collections.emptyList();
        }

        // 步骤4：按 sourceNodeId 做二次过滤，返回匹配结果
        return summaries.stream()
                .filter(s -> Objects.equals(sourceNodeId, s.getSourceNodeId()))
                .collect(Collectors.toList());
    }

    @Override
    public Page<CalculationTemplate> querySuccessfulTasks(Long templateId, String templateName,
                                                          Integer initiator, Pageable pageable) {
        // 结果页只展示确实生成过汇总明细的成功任务。核算任务可能因模板没有
        // 核算节点而被标记为成功，但这类任务没有可展示的数据，默认选中它会
        // 让用户误以为已有结果被清空。
        Specification<CalculationTemplate> spec = (r, q, b) -> {
            Subquery<Long> summaryExists = q.subquery(Long.class);
            Root<CalcNodeSummary> summary = summaryExists.from(CalcNodeSummary.class);
            summaryExists.select(summary.get("id"));
            summaryExists.where(b.equal(summary.get("calculationTemplateId"), r.get("id")));
            return b.and(b.equal(r.get("status"), 2), b.exists(summaryExists));
        };
        if (templateId != null) spec = spec.and((r, q, b) -> b.equal(r.get("templateId"), templateId));
        if (templateName != null && !templateName.isBlank()) {
            List<Long> templateIds = templateRepository.findByNameContainingIgnoreCase(templateName.trim())
                    .stream().map(Template::getId).collect(Collectors.toList());
            if (templateIds.isEmpty()) return Page.empty(pageable);
            spec = spec.and((r, q, b) -> r.get("templateId").in(templateIds));
        }
        if (initiator != null) spec = spec.and((r, q, b) -> b.equal(r.get("taskInitiator"), initiator));
        Page<CalculationTemplate> page = calculationTemplateRepository.findAll(spec, pageable);
        if (page.isEmpty()) return page;
        Map<Long, String> names = templateRepository.findAllById(page.getContent().stream()
                        .map(CalculationTemplate::getTemplateId).distinct().collect(Collectors.toList()))
                .stream().collect(Collectors.toMap(Template::getId, Template::getName));
        return page.map(item -> {
            item.setTemplateName(names.get(item.getTemplateId()));
            return item;
        });
    }

    @Override
    public Page<CalcNodeSummaryResponse> querySuccessfulPage(Long taskId, Long nodeId, Long sourceNodeId,
                                                             String subcategoryCode, String l1, String l2, String l3,
                                                             Pageable pageable) {
        CalculationTemplate task = calculationTemplateRepository.findById(taskId)
                .filter(item -> Integer.valueOf(2).equals(item.getStatus()))
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND, "未找到可查询的成功核算结果"));
        Specification<CalcNodeSummary> spec = (r, q, b) -> b.equal(r.get("calculationTemplateId"), taskId);
        if (nodeId != null) spec = spec.and((r, q, b) -> b.equal(r.get("calculationNodeId"), nodeId));
        if (sourceNodeId != null) spec = spec.and((r, q, b) -> b.equal(r.get("sourceNodeId"), sourceNodeId));
        if (subcategoryCode != null && !subcategoryCode.isBlank()) spec = spec.and((r, q, b) -> b.equal(r.get("emissionSubcategory"), subcategoryCode));
        if (l1 != null && !l1.isBlank()) spec = spec.and((r, q, b) -> b.equal(r.get("energyCategoryL1"), l1));
        if (l2 != null && !l2.isBlank()) spec = spec.and((r, q, b) -> b.equal(r.get("energyCategoryL2"), l2));
        if (l3 != null && !l3.isBlank()) spec = spec.and((r, q, b) -> b.equal(r.get("energyCategoryL3"), l3));
        Map<String, String> subcategories = dataDictService.getDictItems("emission_subcategory");
        Map<String, String> emissionCategories = dataDictService.getDictItems("emission_category");
        Map<String, String> energyCategories = energyCategoryRepository.findAll().stream()
                .collect(Collectors.toMap(EnergyCategory::getCategoryCode, EnergyCategory::getCategoryName,
                        (existing, replacement) -> existing));
        Page<CalcNodeSummary> page = calcNodeSummaryRepository.findAll(spec, pageable);
        Map<Long, String> sourceNodeNames = emissionNodeRepository.findAllById(page.getContent().stream()
                        .map(CalcNodeSummary::getSourceNodeId)
                        .filter(Objects::nonNull).distinct().collect(Collectors.toList()))
                .stream().collect(Collectors.toMap(EmissionNode::getId, EmissionNode::getName,
                        (existing, replacement) -> existing));
        Map<String, String> measurementUnits = calculationNodeDataRepository.findByCalculationNodeIdIn(
                        page.getContent().stream().map(CalcNodeSummary::getCalculationNodeId)
                                .filter(Objects::nonNull).distinct().collect(Collectors.toList()))
                .stream().filter(data -> data.getMeasurementUnit() != null && !data.getMeasurementUnit().isBlank())
                .collect(Collectors.toMap(data -> summaryKey(data.getCalculationNodeId(), data.getEnergyCategoryL1(),
                                data.getEnergyCategoryL2(), data.getEnergyCategoryL3(), data.getEmissionSubcategory()),
                        CalculationNodeData::getMeasurementUnit,
                        (existing, replacement) -> Objects.equals(existing, replacement) ? existing : "多单位"));
        return page.map(item -> {
            String code = item.getEmissionSubcategory();
            String name = subcategories.get(code);
            if (name == null || name.isBlank()) {
                log.warn("核算结果中的排放小类编码无法映射到字典：taskId={}, code={}", task.getId(), code);
                name = "未知排放小类";
            }
            CalcNodeSummaryResponse response = CalcNodeSummaryResponse.from(item, name);
            response.setSourceNodeName(sourceNodeNames.get(item.getSourceNodeId()));
            response.setEnergyCategoryL1Name(energyCategories.getOrDefault(item.getEnergyCategoryL1(), item.getEnergyCategoryL1()));
            response.setEnergyCategoryL2Name(energyCategories.getOrDefault(item.getEnergyCategoryL2(), item.getEnergyCategoryL2()));
            response.setEnergyCategoryL3Name(energyCategories.getOrDefault(item.getEnergyCategoryL3(), item.getEnergyCategoryL3()));
            response.setEmissionCategoryName(emissionCategories.getOrDefault(item.getEmissionCategory(), item.getEmissionCategory()));
            response.setMeasurementUnit(measurementUnits.get(summaryKey(item.getCalculationNodeId(),
                    item.getEnergyCategoryL1(), item.getEnergyCategoryL2(), item.getEnergyCategoryL3(),
                    item.getEmissionSubcategory())));
            return response;
        });
    }

    @Override
    @Transactional
    public CalculationTemplate voidTask(Long taskId, Long userId) {
        CalculationTemplate task = calculationTemplateRepository.findById(taskId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "未找到核算任务"));
        if (!Integer.valueOf(CalculationTemplate.STATUS_SUCCESS).equals(task.getStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "只有成功的核算结果可以作废");
        }
        task.setStatus(CalculationTemplate.STATUS_VOIDED);
        task.setUpdatedBy(userId);
        return calculationTemplateRepository.saveAndFlush(task);
    }

    private String summaryKey(Long calculationNodeId, String l1, String l2, String l3, String subcategory) {
        return String.valueOf(calculationNodeId) + "|" + Objects.toString(l1, "") + "|"
                + Objects.toString(l2, "") + "|" + Objects.toString(l3, "") + "|"
                + Objects.toString(subcategory, "");
    }
}
