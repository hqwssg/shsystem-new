package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.DefaultFactor;
import com.example.carbon.emission.model.entity.EmissionFactorTemplate;
import com.example.carbon.emission.model.repository.DefaultFactorRepository;
import com.example.carbon.emission.model.repository.EmissionFactorTemplateRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import com.example.carbon.emission.model.service.EmissionFactorTemplateService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Optional;

@Service
public class EmissionFactorTemplateServiceImpl implements EmissionFactorTemplateService {

    private static final Logger logger = LoggerFactory.getLogger(EmissionFactorTemplateServiceImpl.class);

    @Autowired
    private EmissionFactorTemplateRepository repository;

    @Autowired
    private DefaultFactorRepository defaultFactorRepository;

    @Autowired
    private TemplateRepository templateRepository;

    /**
     * 查询全部排放因子模版（按创建时间倒序）
     *
     * @return 模版列表；无数据返回空列表
     */
    @Override
    public List<EmissionFactorTemplate> findAll(Long userId) {
        return userId == null ? List.of() : repository.findVisibleTo(userId);
    }

    /**
     * 按主键ID查询单条排放因子模版
     *
     * @param id 模版主键ID
     * @return 模版实体；不存在返回 null
     */
    @Override
    public EmissionFactorTemplate findById(Long id, Long userId) {
        EmissionFactorTemplate entity = repository.findById(id).orElse(null);
        if (entity == null) return null;
        if (Integer.valueOf(1).equals(entity.getIsShared()) || java.util.Objects.equals(entity.getCreatedBy(), userId)) {
            return entity;
        }
        throw new ResponseStatusException(HttpStatus.FORBIDDEN, "无权查看私有因子模板");
    }

    /**
     * 新增排放因子模版
     * <p>
     * 流程：模版名称 trim -> 校验唯一性 -> 保存。名称重复时记 warn 日志并返回 null。
     *
     * @param req 待新增实体（templateName 必填且唯一）
     * @return 新增后的实体；名称重复返回 null
     */
    @Override
    @Transactional
    public EmissionFactorTemplate create(EmissionFactorTemplate req, Long userId) {
        if (req.getTemplateName() != null) {
            req.setTemplateName(req.getTemplateName().trim());
        }
        if (repository.existsByTemplateName(req.getTemplateName())) {
            logger.warn("新增排放因子模版失败，模版名称已存在: {}", req.getTemplateName());
            return null;
        }
        req.setCreatedBy(userId);
        req.setUpdatedBy(userId);
        EmissionFactorTemplate saved = repository.save(req);
        logger.info("新增排放因子模版成功, id={}, name={}", saved.getId(), saved.getTemplateName());
        return saved;
    }

    /**
     * 按主键ID更新排放因子模版
     * <p>
     * 仅更新非空字段：名称（trim 后）、描述、是否共享、状态、更新人。
     *
     * @param id  模版主键ID
     * @param req 待更新字段
     * @return 更新后的实体；记录不存在返回 null
     */
    @Override
    @Transactional
    public EmissionFactorTemplate update(Long id, EmissionFactorTemplate req, Long userId) {
        Optional<EmissionFactorTemplate> optional = repository.findById(id);
        if (optional.isEmpty()) {
            logger.warn("更新排放因子模版失败，记录不存在: id={}", id);
            return null;
        }
        EmissionFactorTemplate entity = optional.get();
        requireOwner(entity, userId);
        if (countReferences(id, userId) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "因子模板已被其他用户的核算模板引用，不能修改");
        }
        if (req.getTemplateName() != null && !req.getTemplateName().isBlank()) {
            entity.setTemplateName(req.getTemplateName().trim());
        }
        entity.setTemplateDescription(req.getTemplateDescription());
        entity.setIsShared(req.getIsShared());
        entity.setStatus(req.getStatus());
        entity.setUpdatedBy(userId);
        EmissionFactorTemplate saved = repository.save(entity);
        logger.info("更新排放因子模版成功, id={}", id);
        return saved;
    }

    /**
     * 按主键ID删除排放因子模版
     *
     * @param id 模版主键ID
     * @return 删除成功返回 true；记录不存在返回 false
     */
    @Override
    @Transactional
    public boolean delete(Long id, Long userId) {
        Optional<EmissionFactorTemplate> optional = repository.findById(id);
        if (optional.isEmpty()) {
            logger.warn("删除排放因子模版失败，记录不存在: id={}", id);
            return false;
        }
        requireOwner(optional.get(), userId);
        if (countReferences(id, null) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "因子模板仍被核算模板引用，不能删除");
        }
        defaultFactorRepository.deleteByTemplateId(id);
        repository.deleteById(id);
        logger.info("删除排放因子模版成功, id={}", id);
        return true;
    }

    /**
     * 切换模版启停状态（1<->0）
     * <p>
     * 当前状态为 null 时按 1 处理，切换后存为 0。
     *
     * @param id        模版主键ID
     * @param updatedBy 更新人ID
     * @return 切换成功返回 true；记录不存在返回 false
     */
    @Override
    @Transactional
    public boolean toggleStatus(Long id, Long userId) {
        Optional<EmissionFactorTemplate> optional = repository.findById(id);
        if (optional.isEmpty()) {
            logger.warn("切换排放因子模版状态失败，记录不存在: id={}", id);
            return false;
        }
        EmissionFactorTemplate entity = optional.get();
        requireOwner(entity, userId);
        int current = entity.getStatus() == null ? 1 : entity.getStatus();
        entity.setStatus(current == 1 ? 0 : 1);
        entity.setUpdatedBy(userId);
        repository.save(entity);
        logger.info("切换排放因子模版状态成功, id={}", id);
        return true;
    }

    /**
     * 切换模版共享状态（1<->0）
     * <p>
     * 当前状态为 null 时按 1 处理，切换后存为 0。
     *
     * @param id        模版主键ID
     * @param updatedBy 更新人ID
     * @return 切换成功返回 true；记录不存在返回 false
     */
    @Override
    @Transactional
    public boolean toggleShared(Long id, Long userId) {
        Optional<EmissionFactorTemplate> optional = repository.findById(id);
        if (optional.isEmpty()) {
            logger.warn("切换排放因子模版共享状态失败，记录不存在: id={}", id);
            return false;
        }
        EmissionFactorTemplate entity = optional.get();
        requireOwner(entity, userId);
        int current = entity.getIsShared() == null ? 1 : entity.getIsShared();
        entity.setIsShared(current == 1 ? 0 : 1);
        entity.setUpdatedBy(userId);
        repository.save(entity);
        logger.info("切换排放因子模版共享状态成功, id={}", id);
        return true;
    }

    /**
     * 统计模版被核算模版引用的次数
     * <p>
     * userId 不为空时仅统计他人引用（用于编辑锁定判断），自己引用不锁定；
     * userId 为 null 时统计全部引用。
     *
     * @param factorTemplateId 因子模版主键ID
     * @param excludeUserId    需排除的用户ID（即当前用户）；为 null 时统计全部引用
     * @return 引用计数；factorTemplateId 为 null 时返回 0
     */
    @Override
    public long countReferences(Long factorTemplateId, Long excludeUserId) {
        if (factorTemplateId == null) {
            return 0;
        }
        if (excludeUserId != null) {
            // 仅统计由他人创建的核算模版引用（自己引用不锁定）
            return templateRepository.countByFactorTemplateIdAndCreatedByNot(factorTemplateId, excludeUserId);
        }
        return templateRepository.countByFactorTemplateId(factorTemplateId);
    }

    /**
     * 拷贝源模版生成新模版（含其下全部缺省因子）
     * <p>
     * 流程：校验源模版存在 -> 校验新名称非空且不重复 -> 保存新模版 ->
     * 拷贝源模版下的全部 DefaultFactor 到新模版下。任一前置校验失败返回 null。
     *
     * @param sourceId  源模版主键ID
     * @param newName   新模版名称（不能重复）
     * @param createdBy 创建人ID
     * @return 新模版实体；源不存在或名称重复返回 null
     */
    @Override
    @Transactional
    public EmissionFactorTemplate copyTemplate(Long sourceId, String newName, Long userId) {
        Optional<EmissionFactorTemplate> sourceOpt = repository.findById(sourceId);
        if (sourceOpt.isEmpty()) {
            logger.warn("拷贝模版失败，源模版不存在: id={}", sourceId);
            return null;
        }
        if (newName == null || newName.isBlank()) {
            logger.warn("拷贝模版失败，新模版名称为空");
            return null;
        }
        if (repository.existsByTemplateName(newName.trim())) {
            logger.warn("拷贝模版失败，模版名称已存在: {}", newName);
            return null;
        }
        EmissionFactorTemplate source = sourceOpt.get();
        if (!Integer.valueOf(1).equals(source.getIsShared()) && !java.util.Objects.equals(source.getCreatedBy(), userId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "无权复制私有因子模板");
        }
        EmissionFactorTemplate copy = new EmissionFactorTemplate();
        copy.setTemplateName(newName.trim());
        copy.setTemplateDescription(source.getTemplateDescription());
        copy.setIsShared(source.getIsShared());
        copy.setCreatedBy(userId);
        copy.setUpdatedBy(userId);
        EmissionFactorTemplate saved = repository.save(copy);

        // 拷贝源模版下的全部缺省因子
        List<DefaultFactor> sourceFactors = defaultFactorRepository.findByTemplateIdOrderBySubcategoryCodeAsc(sourceId);
        for (DefaultFactor sf : sourceFactors) {
            DefaultFactor df = new DefaultFactor();
            df.setTemplateId(saved.getId());
            df.setSubcategoryCode(sf.getSubcategoryCode());
            df.setSubcategoryName(sf.getSubcategoryName());
            df.setFactorSource(sf.getFactorSource());
            df.setFactorId(sf.getFactorId());
            df.setFactorName(sf.getFactorName());
            df.setFactorValue(sf.getFactorValue());
            df.setFactorUnit(sf.getFactorUnit());
            df.setFactorDescription(sf.getFactorDescription());
            df.setRemark(sf.getRemark());
            df.setStatus(sf.getStatus());
            df.setCreatedBy(userId);
            defaultFactorRepository.save(df);
        }
        logger.info("拷贝模版成功，源id={}, 新id={}, 因子数={}", sourceId, saved.getId(), sourceFactors.size());
        return saved;
    }

    private void requireOwner(EmissionFactorTemplate entity, Long userId) {
        if (userId == null || !java.util.Objects.equals(entity.getCreatedBy(), userId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "仅创建人可以管理因子模板");
        }
    }
}
