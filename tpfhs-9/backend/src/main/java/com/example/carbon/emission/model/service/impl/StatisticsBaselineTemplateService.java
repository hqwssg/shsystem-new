package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.SystemConfig;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.SystemConfigRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * Stores one statistics baseline calculation template for each registered company.
 * The key is stable and can also be consumed by prediction modules.
 */
@Service
public class StatisticsBaselineTemplateService {
    public static final String KEY_PREFIX = "carbon.statistics.baseline-template.";
    private static final String REMARK = "该分公司统计查询及预测模型默认使用的核算模版";

    public record Baseline(Long companyDeptId, String companyName, Long templateId,
                           String templateName, String configKey) { }

    private final TemplateRepository templates;
    private final SystemConfigRepository configs;
    private final CompanyOwnershipService companies;

    public StatisticsBaselineTemplateService(TemplateRepository templates,
                                             SystemConfigRepository configs,
                                             CompanyOwnershipService companies) {
        this.templates = templates;
        this.configs = configs;
        this.companies = companies;
    }

    @Transactional
    public Baseline set(Long templateId) {
        CarbonSecurityContext context = CarbonSecurityContext.current();
        if (!context.hasPermission("carbon:model:edit")) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "没有设置统计基准模版的权限");
        }
        Template template = templates.findById(templateId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "核算模版不存在"));
        if (!Integer.valueOf(2).equals(template.getTemplateType())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "仅核算模版可设为统计基准模版");
        }
        Long companyDeptId = companies.require(template.getDeptId());
        CompanyOwnershipService.Company company = companies.options().stream()
                .filter(item -> companyDeptId.equals(item.deptId()))
                .findFirst()
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.FORBIDDEN, "模板归属公司不在当前数据权限范围内"));

        String key = key(companyDeptId);
        SystemConfig config = configs.findFirstByConfigKeyOrderByConfigIdDesc(key)
                .orElseGet(SystemConfig::new);
        config.setConfigKey(key);
        config.setConfigName(company.deptName() + "统计基准模版ID");
        config.setConfigValue(String.valueOf(template.getId()));
        config.setRemark(REMARK);
        config.setConfigType("N");
        config.setUpdateBy(context.userName());
        if (config.getConfigId() == null) {
            config.setCreateBy(context.userName());
        }
        configs.save(config);
        return new Baseline(companyDeptId, company.deptName(), template.getId(), template.getName(), key);
    }

    @Transactional(readOnly = true)
    public List<Baseline> accessible() {
        Map<Long, Template> accessibleTemplates = templates.findAllByOrderByCreatedAtDesc().stream()
                .filter(t -> Integer.valueOf(2).equals(t.getTemplateType()))
                .collect(Collectors.toMap(Template::getId, Function.identity(), (left, right) -> left));
        return companies.accessibleOptions().stream().map(company -> {
            String key = key(company.deptId());
            Long templateId = configs.findFirstByConfigKeyOrderByConfigIdDesc(key)
                    .map(SystemConfig::getConfigValue)
                    .map(this::parseLong)
                    .orElse(null);
            Template template = templateId == null ? null : accessibleTemplates.get(templateId);
            if (template == null || !company.deptId().equals(template.getDeptId())) {
                return new Baseline(company.deptId(), company.deptName(), null, null, key);
            }
            return new Baseline(company.deptId(), company.deptName(), template.getId(), template.getName(), key);
        }).toList();
    }

    /** 核算发布链路使用的无页面上下文判定，不依赖当前登录人的数据范围。 */
    @Transactional(readOnly = true)
    public boolean isBaseline(Long companyDeptId, Long templateId) {
        if (companyDeptId == null || templateId == null) {
            return false;
        }
        return configs.findFirstByConfigKeyOrderByConfigIdDesc(key(companyDeptId))
                .map(SystemConfig::getConfigValue)
                .map(this::parseLong)
                .filter(templateId::equals)
                .isPresent();
    }

    private String key(Long companyDeptId) {
        return KEY_PREFIX + companyDeptId;
    }

    private Long parseLong(String value) {
        try {
            return Long.valueOf(value);
        } catch (NumberFormatException ignored) {
            return null;
        }
    }
}
