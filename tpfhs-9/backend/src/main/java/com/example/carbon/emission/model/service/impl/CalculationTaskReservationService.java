package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;

/** 在独立事务中预留“模板+周期”任务，数据库唯一约束负责并发最终仲裁。 */
@Service
public class CalculationTaskReservationService {

    private final CalculationTemplateRepository repository;
    @org.springframework.beans.factory.annotation.Autowired
    private com.example.carbon.emission.model.repository.TemplateRepository templates;
    @org.springframework.beans.factory.annotation.Autowired
    private CompanyOwnershipService companies;

    public CalculationTaskReservationService(CalculationTemplateRepository repository) {
        this.repository = repository;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public CalculationTemplate reserve(Long templateId, LocalDate start, LocalDate end, Long dataRevision) {
        return reserve(templateId, start, end, dataRevision, 1, 0L, null);
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public CalculationTemplate reserve(Long templateId, LocalDate start, LocalDate end, Long dataRevision,
                                       int taskInitiator, Long initiatorId, String initiatorName) {
        long revision = dataRevision == null ? 0L : dataRevision;
        // Serialize against explicit ownership changes, including historical confirmation.
        var template = templates.findForCompanyUpdate(templateId).orElseThrow();
        Long company = companies.registeredId(template.getDeptId());
        if (company == null) throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.BAD_REQUEST, "请先为核算模板设置已登记的归属公司");
        repository.findFirstByTemplateIdAndCalculationCycleStartDateAndCalculationCycleEndDateAndDataRevisionOrderByIdDesc(
                        templateId, start, end, revision)
                .ifPresent(existing -> {
                    if (Integer.valueOf(CalculationTemplate.STATUS_VOIDED).equals(existing.getStatus())) {
                        // A voided result is retained for audit and no longer reserves the cycle.
                    } else if (Integer.valueOf(CalculationTemplate.STATUS_FAILED).equals(existing.getStatus())) {
                        // A failed task has no valid result and must not block a
                        // retry after its cause has been corrected. Child node
                        // snapshots/results are removed by the database cascade.
                        repository.delete(existing);
                        repository.flush();
                    } else {
                        throw new DataIntegrityViolationException(
                                "同一模板周期已有未失败核算任务：" + existing.getId());
                    }
                });
        CalculationTemplate task = new CalculationTemplate();
        task.setTemplateId(templateId);
        task.setCompanyDeptId(company);
        task.setTaskInitiator(taskInitiator);
        task.setInitiatorId(initiatorId == null ? 0L : initiatorId);
        task.setInitiatorName(initiatorName);
        task.setStatus(1);
        task.setDataRevision(revision);
        task.setCalculationCycleStartDate(start);
        task.setCalculationCycleEndDate(end);
        task.setCalculationStartTime(LocalDateTime.now());
        return repository.saveAndFlush(task);
    }
}
