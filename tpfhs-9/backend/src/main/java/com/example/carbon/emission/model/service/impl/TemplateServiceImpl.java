package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.CreateTemplateRequest;
import com.example.carbon.emission.model.dto.TemplateDTO;
import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.EmissionNodeInfo;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.entity.User;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.EmissionNodeInfoRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import com.example.carbon.emission.model.repository.UserRepository;
import com.example.carbon.emission.model.service.TemplateService;
import com.example.carbon.emission.model.security.CarbonDataScopeService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.HashMap;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class TemplateServiceImpl implements TemplateService {
    
    @Autowired
    private TemplateRepository templateRepository;
    
    @Autowired
    private UserRepository userRepository;
    
    @Autowired
    private EmissionNodeRepository nodeRepository;
    
    @Autowired
    private EmissionNodeConfigRepository configRepository;

    @Autowired
    private EmissionNodeInfoRepository nodeInfoRepository;

    @Autowired(required = false)
    private CarbonDataScopeService dataScope;

    @Autowired
    private CompanyOwnershipService companies;

    @Autowired
    private org.springframework.jdbc.core.JdbcTemplate jdbc;
    @jakarta.persistence.PersistenceContext
    private jakarta.persistence.EntityManager entityManager;

    @Autowired
    private TaskScheduleConfigService taskScheduleConfigService;
    
    @Override
    public List<TemplateDTO> getAllTemplates() {
        return templateRepository.findAllByOrderByCreatedAtDesc().stream()
            .filter(template -> dataScope == null || dataScope.canReadSafely(template))
            .map(this::convertToDTO)
            .collect(Collectors.toList());
    }
    
    @Override
    public TemplateDTO getTemplateById(Long id) {
        requireTemplate(id, false);
        Template template = templateRepository.findById(id)
            .orElseThrow(() -> new RuntimeException("模版不存在"));
        return convertToDTO(template);
    }
    
    @Override
    @Transactional
    public TemplateDTO createTemplate(CreateTemplateRequest request) {
        if (request.getName() == null || request.getName().isBlank()) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "模版名称不能为空");
        }
        if (request.getTemplateType() != null
                && request.getTemplateType() != 1 && request.getTemplateType() != 2) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "模版类型只能为1或2");
        }
        Template template = new Template();
        template.setName(request.getName());
        template.setDescription(request.getDescription());
        if (Integer.valueOf(2).equals(request.getTemplateType()) || request.getCompanyDeptId() != null)
            template.setDeptId(companies.require(request.getCompanyDeptId()));
        else if (dataScope != null) template.setDeptId(dataScope.current().deptId());
        template.setCreatedBy(request.getCreatedBy());
        template.setUpdatedBy(request.getCreatedBy());
        // 模版类型：未指定时默认为1（节点模版）
        template.setTemplateType(request.getTemplateType() != null ? request.getTemplateType() : 1);

        Template saved = templateRepository.save(template);
        return convertToDTO(saved);
    }
    
    @Override
    @Transactional
    public TemplateDTO updateTemplate(Long id, String name, Long updatedBy) {
        requireTemplate(id, true);
        Template template = templateRepository.findById(id)
            .orElseThrow(() -> new RuntimeException("模版不存在"));

        if (name != null && !name.isEmpty()) {
            template.setName(name);
        }
        template.setUpdatedBy(updatedBy);
        // 模版被修改，校验结果自动重置为未检查
        resetCheckStatus(template);

        Template saved = templateRepository.save(template);
        return convertToDTO(saved);
    }

    @Override
    @Transactional
    public TemplateDTO updateTemplate(Long id, String description, Boolean enabled, Integer templateType, String taskConfig, Long factorTemplateId, Long updatedBy) {
        requireTemplate(id, true);
        Template template = templateRepository.findById(id)
            .orElseThrow(() -> new RuntimeException("模版不存在"));

        int effectiveTemplateType = templateType != null ? templateType
                : (template.getTemplateType() == null ? 1 : template.getTemplateType());
        if (effectiveTemplateType != 1 && effectiveTemplateType != 2) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_REQUEST, "模版类型只能为1或2");
        }
        String effectiveTaskConfig = taskConfig != null ? taskConfig : template.getTaskConfig();
        if (effectiveTemplateType == 2 && (taskConfig != null || Boolean.TRUE.equals(enabled))) {
            effectiveTaskConfig = taskScheduleConfigService.normalize(effectiveTaskConfig);
        }

        if (description != null) {
            template.setDescription(description);
        }
        if (enabled != null) {
            template.setEnabled(enabled);
        }
        // 模版类型：1-节点模版；2-核算模版
        if (templateType != null) {
            template.setTemplateType(effectiveTemplateType);
        }
        if (taskConfig != null || (effectiveTemplateType == 2 && Boolean.TRUE.equals(enabled))) {
            template.setTaskConfig(effectiveTaskConfig);
        }
        // factorTemplateId 允许设为 null（清除关联）
        template.setFactorTemplateId(factorTemplateId);
        template.setUpdatedBy(updatedBy);
        // 模版被修改，校验结果自动重置为未检查
        resetCheckStatus(template);

        Template saved = templateRepository.save(template);
        return convertToDTO(saved);
    }

    /**
     * 模版被修改后重置校验状态为未检查（check_result=0，清空校验时间与告警信息）
     *
     * @param template 待重置的模版实体
     */
    private void resetCheckStatus(Template template) {
        template.setCheckResult(0);
        template.setCheckTime(null);
        template.setCheckMessage(null);
    }
    
    @Override
    @Transactional
    public TemplateDTO copyTemplate(Long sourceId, String newName, Long createdBy) {
        return copyTemplate(sourceId, newName, createdBy, null);
    }

    @Override
    @Transactional
    public TemplateDTO copyTemplate(Long sourceId, String newName, Long createdBy, Long companyDeptId) {
        requireTemplate(sourceId, false);
        Template source = templateRepository.findById(sourceId)
            .orElseThrow(() -> new RuntimeException("源模版不存在"));
        
        Template copy = new Template();
        copy.setName(newName);
        copy.setDescription(source.getDescription());
        if (Integer.valueOf(2).equals(source.getTemplateType()) || companyDeptId != null)
            copy.setDeptId(companies.require(companyDeptId));
        else if (dataScope != null) copy.setDeptId(dataScope.current().deptId());
        copy.setCreatedBy(createdBy);
        copy.setUpdatedBy(createdBy);
        copy.setVersion(1);
        copy.setEnabled(source.getEnabled());
        copy.setTemplateType(source.getTemplateType() != null ? source.getTemplateType() : 1);
        copy.setTaskConfig(source.getTaskConfig());
        // 因子模版是可共享资源；复制核算模版时保留引用，不复制因子模版本身。
        copy.setFactorTemplateId(source.getFactorTemplateId());
        resetCheckStatus(copy);
        
        Template saved = templateRepository.save(copy);
        
        List<EmissionNode> sourceNodes = nodeRepository.findByTemplateId(sourceId);
        
        Map<Long, Long> nodeIdMap = new HashMap<>();
        List<EmissionNode> pending = new ArrayList<>(sourceNodes);
        while (!pending.isEmpty()) {
            int before = pending.size();
            pending.removeIf(sourceNode -> {
                Long sourceParentId = sourceNode.getParentId();
                if (sourceParentId != null && !nodeIdMap.containsKey(sourceParentId)) {
                    return false;
                }
                EmissionNode newNode = new EmissionNode();
                newNode.setName(sourceNode.getName());
                newNode.setTypeId(sourceNode.getTypeId());
                newNode.setParentId(sourceParentId == null ? null : nodeIdMap.get(sourceParentId));
                newNode.setTemplateId(saved.getId());
                // 保留最初源节点关系，报告按部门主体节点筛选时可追溯多次复制后的节点。
                Long sourceNodeId = sourceNode.getSourceNodeId() != null && sourceNode.getSourceNodeId() > 0
                        ? sourceNode.getSourceNodeId() : sourceNode.getId();
                newNode.setSourceNodeId(sourceNodeId);
                newNode.setLocomotiveType(sourceNode.getLocomotiveType());
                newNode.setSortOrder(sourceNode.getSortOrder());
                newNode.setCreatedBy(createdBy);
                newNode.setUpdatedBy(createdBy);
                EmissionNode savedNode = nodeRepository.save(newNode);
                nodeIdMap.put(sourceNode.getId(), savedNode.getId());
                return true;
            });
            if (pending.size() == before) {
                throw new IllegalStateException("源模版节点存在孤儿或循环关系，无法复制");
            }
        }
        
        for (EmissionNode sourceNode : sourceNodes) {
            configRepository.findByNodeId(sourceNode.getId()).ifPresent(sourceConfig -> {
                EmissionNodeConfig newConfig = new EmissionNodeConfig();
                newConfig.setNodeId(nodeIdMap.get(sourceNode.getId()));
                newConfig.setEmissionCategory(sourceConfig.getEmissionCategory());
                newConfig.setEmissionSubcategory(sourceConfig.getEmissionSubcategory());
                newConfig.setCarbonEmissionFactor(sourceConfig.getCarbonEmissionFactor());
                newConfig.setCarbonEmissionFactorUnit(sourceConfig.getCarbonEmissionFactorUnit());
                newConfig.setCarbonEmissionFactorDescription(sourceConfig.getCarbonEmissionFactorDescription());
                newConfig.setCollectionDescription(sourceConfig.getCollectionDescription());
                newConfig.setEquipmentCode(sourceConfig.getEquipmentCode());
                newConfig.setCollectionPointType(sourceConfig.getCollectionPointType());
                newConfig.setCollectionPointId(sourceConfig.getCollectionPointId());
                newConfig.setCollectionPointStatus(sourceConfig.getCollectionPointStatus());
                newConfig.setCreatedBy(createdBy);
                newConfig.setUpdatedBy(createdBy);
                
                configRepository.save(newConfig);
            });

            nodeInfoRepository.findByNodeId(sourceNode.getId()).ifPresent(sourceInfo -> {
                EmissionNodeInfo newInfo = new EmissionNodeInfo();
                newInfo.setNodeId(nodeIdMap.get(sourceNode.getId()));
                newInfo.setNodeCode(sourceInfo.getNodeCode());
                newInfo.setShortName(sourceInfo.getShortName());
                newInfo.setIncludeInCalculation(sourceInfo.getIncludeInCalculation());
                newInfo.setNodeCategory(sourceInfo.getNodeCategory());
                newInfo.setUnitDescription(sourceInfo.getUnitDescription());
                newInfo.setOrgBoundaryDescription(sourceInfo.getOrgBoundaryDescription());
                newInfo.setOperationBoundaryDescription(sourceInfo.getOperationBoundaryDescription());
                newInfo.setCreatedBy(createdBy);
                newInfo.setUpdatedBy(createdBy);
                nodeInfoRepository.save(newInfo);
            });
        }
        
        return convertToDTO(saved);
    }
    
    @Override
    @Transactional
    public void deleteTemplate(Long id) {
        requireTemplate(id, true);
        if (!templateRepository.existsById(id)) {
            throw new RuntimeException("模版不存在");
        }
        templateRepository.deleteById(id);
    }
    
    @Override
    @Transactional
    public TemplateDTO assignCompany(Long id, Long companyDeptId, boolean confirmLegacyTasks) {
        requireTemplate(id, true);
        companies.require(companyDeptId);
        Template template = templateRepository.findForCompanyUpdate(id).orElseThrow();
        entityManager.refresh(template);
        // Recheck ownership after acquiring the lock used by task reservation.
        requireTemplate(id, true);
        Integer active = jdbc.queryForObject("select count(*) from emission_calculation_template where template_id=? and status in (0,1)", Integer.class, id);
        if (active != null && active > 0) throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.CONFLICT, "模板有在途任务，请结束后再设置公司归属");
        Integer other = jdbc.queryForObject("select count(*) from emission_calculation_template where template_id=? and company_dept_id is not null and company_dept_id<>?", Integer.class, id, companyDeptId);
        if (other != null && other > 0) throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.CONFLICT, "已有其他公司的任务快照，请另存模板后选择新公司，不能改变历史归属");
        template.setDeptId(companyDeptId);
        template.setUpdatedBy(com.example.carbon.emission.model.security.CarbonSecurityContext.current().userId());
        if (confirmLegacyTasks) jdbc.update("update emission_calculation_template set company_dept_id=?,updated_by=?,updated_at=CURRENT_TIMESTAMP where template_id=? and company_dept_id is null", companyDeptId, template.getUpdatedBy(), id);
        return convertToDTO(templateRepository.save(template));
    }

    private TemplateDTO convertToDTO(Template template) {
        TemplateDTO dto = new TemplateDTO();
        dto.setId(template.getId());
        dto.setName(template.getName());
        dto.setDescription(template.getDescription());
        dto.setDeptId(template.getDeptId());
        if (companies != null) companies.registered().stream()
                .filter(c -> c.deptId().equals(template.getDeptId())).findFirst().ifPresent(c -> {
                    dto.setCompanyDeptId(c.deptId()); dto.setCompanyName(c.deptName());
                });
        dto.setCreatedBy(template.getCreatedBy());
        dto.setCreatedAt(template.getCreatedAt());
        dto.setUpdatedBy(template.getUpdatedBy());
        dto.setUpdatedAt(template.getUpdatedAt());
        dto.setVersion(template.getVersion());
        dto.setEnabled(template.getEnabled());
        dto.setTemplateType(template.getTemplateType() != null ? template.getTemplateType() : 1);
        dto.setTaskConfig(template.getTaskConfig());
        dto.setFactorTemplateId(template.getFactorTemplateId());
        dto.setCheckResult(template.getCheckResult() != null ? template.getCheckResult() : 0);
        dto.setCheckTime(template.getCheckTime());
        dto.setCheckMessage(template.getCheckMessage());
        
        if (template.getCreatedBy() != null) {
            userRepository.findById(template.getCreatedBy())
                .ifPresent(user -> dto.setCreatedByName(user.getNickName()));
        }
        if (template.getUpdatedBy() != null) {
            userRepository.findById(template.getUpdatedBy())
                .ifPresent(user -> dto.setUpdatedByName(user.getNickName()));
        }
        
        return dto;
    }

    private void requireTemplate(Long id, boolean write) {
        if (dataScope != null) dataScope.requireTemplate(id, write);
    }
}
