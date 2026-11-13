package com.railway.carbon.platform.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public final class Dtos {

    private Dtos() {
    }

    public record Org(String orgId, String orgName, Integer orgLevel, String province) {
    }

    public record Var(String varId, String varName, String unit, String category,
                      Boolean traction, Boolean target, Integer sortOrder) {
    }

    public record ActivityRow(Long id, String orgId, String orgName, LocalDate period,
                              String varId, String varName, BigDecimal value,
                              BigDecimal reportedValue, String unit, String sourceStatus,
                              Boolean estimated, String qualityStatus, String dataFlag,
                              String batchId, String dataVersion, LocalDateTime createdAt) {
    }

    public record EnergyItem(String varId, String varName, BigDecimal value,
                             BigDecimal reportedValue, String unit, String sourceStatus,
                             Boolean estimated, String qualityStatus, String dataFlag) {
    }

    public record EnergyEmission(BigDecimal totalReportedTco2,
                                 BigDecimal totalComparableTco2,
                                 BigDecimal electricityFactor,
                                 BigDecimal heatFactor,
                                 String factorVersion,
                                 String factorSource) {
    }

    public record MonthlyEnergy(String orgId, String orgName, LocalDate period,
                                String periodLabel, String status, String batchId,
                                Map<String, Integer> qualitySummary,
                                List<EnergyItem> items,
                                EnergyEmission emission) {
    }

    public record EnergyCompareResult(int result, boolean exists, boolean equal,
                                      String orgId, String periodLabel, String varId,
                                      BigDecimal inputValue, BigDecimal storedValue,
                                      String message) {
    }

    public record FactorRow(Long factorId, String varId, String varName,
                            BigDecimal factorValue, String factorUnit, String factorVersion,
                            LocalDate effectiveFrom, LocalDate effectiveTo,
                            String factorSource, Boolean caliberChange, String policyBasis) {
    }

    public record FactorRequest(
            @NotBlank(message = "品种不能为空") String varId,
            @NotNull(message = "因子值不能为空") @DecimalMin(value = "0", message = "因子值不能为负") BigDecimal factorValue,
            @NotBlank(message = "因子单位不能为空") String factorUnit,
            @NotBlank(message = "因子版本不能为空") String factorVersion,
            @NotNull(message = "生效起始日不能为空") LocalDate effectiveFrom,
            LocalDate effectiveTo,
            String factorSource,
            Boolean caliberChange,
            String policyBasis) {
    }

    public record PolicyFactorRow(Long id, String factorId, String factorName, LocalDate period,
                                  BigDecimal value, String unit, String category,
                                  String sourceLevel, String sourceStatus, Boolean scenarioOnly,
                                  String dataSource) {
    }

    public record PolicyFactorRequest(
            @NotBlank(message = "因子编码不能为空") String factorId,
            @NotBlank(message = "因子名称不能为空") String factorName,
            @NotBlank(message = "月份不能为空") @Pattern(regexp = "\\d{4}-(0[1-9]|1[0-2])", message = "月份格式应为 YYYY-MM") String period,
            @NotNull(message = "数值不能为空") BigDecimal value,
            @NotBlank(message = "单位不能为空") String unit,
            String category,
            String sourceLevel,
            String sourceStatus,
            Boolean scenarioOnly,
            String dataSource) {
    }

    public record CaliberRuleRow(String ruleId, String orgId, String orgName,
                                 String ruleType, LocalDate effectiveFrom, LocalDate effectiveTo,
                                 BigDecimal ruleValue, String unit, String ruleVersion,
                                 String source, String note) {
    }

    public record CaliberRuleRequest(
            @NotBlank(message = "规则编码不能为空") String ruleId,
            @NotBlank(message = "组织不能为空") String orgId,
            @NotBlank(message = "规则类型不能为空") String ruleType,
            @NotNull(message = "生效起始日不能为空") LocalDate effectiveFrom,
            LocalDate effectiveTo,
            @NotNull(message = "规则值不能为空") @DecimalMin(value = "0", message = "规则值不能为负") BigDecimal ruleValue,
            @NotBlank(message = "单位不能为空") String unit,
            @NotBlank(message = "规则版本不能为空") String ruleVersion,
            String source,
            String note) {
    }

    public record CalendarEventRow(Long id, String eventId, String eventType, String eventName,
                                   LocalDate startDate, LocalDate endDate, String orgId,
                                   String impactDirection, String source, String note) {
    }

    public record CalendarEventRequest(
            @NotBlank(message = "事件编码不能为空") String eventId,
            @NotBlank(message = "事件类型不能为空") String eventType,
            @NotBlank(message = "事件名称不能为空") String eventName,
            @NotNull(message = "开始日期不能为空") LocalDate startDate,
            @NotNull(message = "结束日期不能为空") LocalDate endDate,
            String orgId,
            String impactDirection,
            String source,
            String note) {
    }

    public record AnomalyRow(Long id, String sourceType, String orgId, String orgName,
                             LocalDate period, String varId, String varName, String level,
                             String category, BigDecimal score, BigDecimal confidence,
                             String channel, String channels, String status,
                             String finalDisposition, String evidence, String contextFlags,
                             BigDecimal value, BigDecimal referenceValue, String reviewer,
                             LocalDateTime reviewedAt, String reviewNote,
                             LocalDateTime createdAt, String algorithmVersion) {
    }

    public record ReviewRequest(
            @NotBlank(message = "处置动作不能为空") String action,
            BigDecimal correctionValue,
            @NotBlank(message = "审核人不能为空") String reviewer,
            String note) {
    }

    public record ModelRow(String modelId, String orgId, String orgName, String modelType,
                           String version, String status, Boolean champion, String targetVar,
                           Integer windowSize, Integer horizon, Object metrics,
                           LocalDate trainStart, LocalDate trainEnd, Integer nSamples,
                           String artifactPath, LocalDateTime trainedAt) {
    }

    public record JobRow(String jobId, String jobType, String status, Object params,
                         Object result, String error, String operator,
                         LocalDateTime createdAt, LocalDateTime startedAt, LocalDateTime finishedAt) {
    }

    public record ForecastRow(Long id, String modelId, String orgId, String orgName,
                              LocalDate period, String scenario, String targetVar,
                              BigDecimal point, BigDecimal lowerBound, BigDecimal upperBound,
                              BigDecimal reportedPoint, BigDecimal comparablePoint,
                              BigDecimal confidenceLevel, LocalDateTime createdAt) {
    }

    public record HistoryRow(String orgId, String orgName, LocalDate period,
                             BigDecimal totalReportedTco2, BigDecimal totalComparableTco2,
                             BigDecimal electricityFactor, BigDecimal heatFactor,
                             String factorVersion) {
    }

    public record IngestRecord(
            @NotBlank(message = "组织不能为空") String orgId,
            @NotBlank(message = "月份不能为空") @Pattern(regexp = "\\d{4}-(0[1-9]|1[0-2])", message = "月份格式应为 YYYY-MM") String period,
            @NotBlank(message = "品种不能为空") String varId,
            @NotNull(message = "活动量不能为空") @DecimalMin(value = "0", message = "活动量不能为负") BigDecimal value,
            BigDecimal reportedValue,
            String unit) {
    }

    public record IngestRequest(
            @NotEmpty(message = "至少一条活动数据") List<IngestRecord> records,
            String idempotencyKey,
            String operator,
            Boolean runAnomaly,
            String factorVersion,
            Boolean override,
            String overrideReason) {
    }

    public record PolicyFactorBatchRequest(@NotEmpty(message = "至少一个因子") List<PolicyFactorRequest> factors,
                                           String operator) {
    }

    public record TrainRequest(List<String> orgIds, String mode, String asOf,
                               Boolean force, String operator) {
    }

    public record ForecastGenerateRequest(List<String> orgIds, Integer horizon,
                                          String scenario, String asOf,
                                          Boolean writeDb, String operator,
                                          Boolean asyncRun) {
    }

    public record ApiInfo(String method, String path, String description, String sample) {
    }

    public record DashboardSummary(String orgId, String orgName, Map<String, Object> latestActual,
                                   Map<String, Object> forecastNext12m, Integer pendingAnomalies) {
    }
}
