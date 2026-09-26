package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CalculationTemplate;
import com.example.carbon.emission.model.repository.CalculationTemplateRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;

/** 在独立事务中预留“模板+周期”任务，数据库唯一约束负责并发最终仲裁。 */
@Service
public class CalculationTaskReservationService {

    private final CalculationTemplateRepository repository;

    public CalculationTaskReservationService(CalculationTemplateRepository repository) {
        this.repository = repository;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public CalculationTemplate reserve(Long templateId, LocalDate start, LocalDate end) {
        CalculationTemplate task = new CalculationTemplate();
        task.setTemplateId(templateId);
        task.setTaskInitiator(1);
        task.setStatus(1);
        task.setCalculationCycleStartDate(start);
        task.setCalculationCycleEndDate(end);
        task.setCalculationStartTime(LocalDateTime.now());
        return repository.saveAndFlush(task);
    }
}
