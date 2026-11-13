package com.example.carbon.emission.model.dto;

import java.time.LocalDate;
import java.time.LocalDateTime;

/** A successful calculation result that can be selected for uncertainty analysis. */
public record CalculationTaskOption(
        Long taskId,
        Long templateId,
        String templateName,
        Long companyDeptId,
        String companyName,
        LocalDate cycleStart,
        LocalDate cycleEnd,
        Integer status,
        LocalDateTime completedAt) {
}
