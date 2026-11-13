package com.example.carbon.emission.model.service.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeParseException;
import java.util.Set;

/**
 * 核算任务配置的唯一解析与校验入口，避免保存、调度和核算各自解释 taskConfig。
 */
@Service
public class TaskScheduleConfigService {

    private static final Set<String> CYCLES = Set.of(
            "DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY");

    private final ObjectMapper objectMapper;

    public TaskScheduleConfigService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public JsonNode validate(String json) {
        if (json == null || json.isBlank()) {
            throw badRequest("核算任务配置不能为空");
        }
        final ObjectNode config;
        try {
            JsonNode parsed = objectMapper.readTree(json);
            if (parsed == null || !parsed.isObject()) {
                throw badRequest("核算任务配置必须是JSON对象");
            }
            config = (ObjectNode) parsed;
        } catch (Exception ex) {
            if (ex instanceof ResponseStatusException statusException) {
                throw statusException;
            }
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "核算任务配置不是合法JSON", ex);
        }
        normalizeWeekdays(config);

        String cycleType = requiredText(config, "cycleType").toUpperCase();
        if (!CYCLES.contains(cycleType)) {
            throw badRequest("不支持的核算周期类型: " + cycleType);
        }
        try {
            LocalTime.parse(requiredText(config, "executionTime"));
        } catch (DateTimeParseException ex) {
            throw badRequest("执行时间必须使用HH:mm格式");
        }

        LocalDate start = optionalDate(config, "startDate");
        LocalDate end = optionalDate(config, "endDate");
        if (start != null && end != null && start.isAfter(end)) {
            throw badRequest("任务开始日期不能晚于结束日期");
        }
        int delayDays = optionalInt(config, "delayDays", 0);
        if (delayDays < 0) {
            throw badRequest("延迟天数不能为负数");
        }
        int interval = optionalInt(config, "interval", 1);
        if (interval < 1) {
            throw badRequest("执行间隔必须大于等于1");
        }

        // 兼容早期已保存的任务配置：旧版本未写入固定执行日时，按页面默认值使用第 1 天/周一。
        // 新配置仍由前端明确写入这些字段；这里只避免历史启用模板在调度线程中持续报错。
        normalizeExecutionDays(config, cycleType);
        switch (cycleType) {
            case "WEEKLY" -> validateArray(config, "weekdays", 1, 7);
            case "MONTHLY" -> validateArray(config, "monthDays", 1, 31);
            case "QUARTERLY" -> validateArray(config, "quarterDays", 1, 31);
            case "YEARLY" -> {
                JsonNode months = validateArray(config, "yearMonths", 1, 12);
                JsonNode days = validateArray(config, "yearDays", 1, 31);
                if (months.size() != days.size()) {
                    throw badRequest("年度执行月份与日期必须一一对应");
                }
            }
            default -> {
                // DAILY没有额外执行日字段。
            }
        }
        return config;
    }

    private void normalizeExecutionDays(ObjectNode config, String cycleType) {
        switch (cycleType) {
            case "WEEKLY" -> ensureDefaultArray(config, "weekdays", 1);
            case "MONTHLY" -> ensureDefaultArray(config, "monthDays", 1);
            case "QUARTERLY" -> ensureDefaultArray(config, "quarterDays", 1);
            case "YEARLY" -> {
                ensureDefaultArray(config, "yearMonths", 1);
                ensureDefaultArray(config, "yearDays", 1);
            }
            default -> {
                // DAILY 不需要执行日字段。
            }
        }
    }

    private void ensureDefaultArray(ObjectNode config, String field, int defaultValue) {
        JsonNode values = config.get(field);
        if (values == null || values.isNull()) {
            ArrayNode defaults = objectMapper.createArrayNode();
            defaults.add(defaultValue);
            config.set(field, defaults);
        }
    }

    /** 返回只包含规范字段的任务配置JSON；weekDays仅作为历史输入别名。 */
    public String normalize(String json) {
        return validate(json).toString();
    }

    /**
     * Automatic calculation is opt-in. Legacy configurations without the flag
     * remain disabled so an unrelated data change cannot unexpectedly start a task.
     */
    public boolean isAutoCalculationEnabled(String json) {
        if (json == null || json.isBlank()) {
            return false;
        }
        try {
            JsonNode config = objectMapper.readTree(json);
            JsonNode enabled = config == null ? null : config.get("autoCalculationEnabled");
            return enabled != null && enabled.isBoolean() && enabled.asBoolean();
        } catch (Exception ex) {
            return false;
        }
    }

    private void normalizeWeekdays(ObjectNode config) {
        JsonNode legacy = config.get("weekDays");
        JsonNode canonical = config.get("weekdays");
        if (legacy != null && canonical != null && !legacy.equals(canonical)) {
            throw badRequest("weekDays与weekdays不能同时提供不同值");
        }
        if (canonical == null && legacy != null) {
            config.set("weekdays", legacy);
        }
        config.remove("weekDays");
    }

    public LocalDate[] calculateCycle(String json, LocalDate today) {
        JsonNode config = validate(json);
        int delayDays = optionalInt(config, "delayDays", 0);
        LocalDate adjusted = today.minusDays(delayDays);
        return switch (requiredText(config, "cycleType").toUpperCase()) {
            case "DAILY" -> new LocalDate[]{adjusted.minusDays(1), adjusted.minusDays(1)};
            case "WEEKLY" -> {
                LocalDate monday = adjusted.with(DayOfWeek.MONDAY).minusWeeks(1);
                yield new LocalDate[]{monday, monday.plusDays(6)};
            }
            case "MONTHLY" -> {
                LocalDate month = adjusted.minusMonths(1);
                yield new LocalDate[]{month.withDayOfMonth(1), month.withDayOfMonth(month.lengthOfMonth())};
            }
            case "QUARTERLY" -> previousQuarter(adjusted);
            case "YEARLY" -> new LocalDate[]{
                    LocalDate.of(adjusted.getYear() - 1, 1, 1),
                    LocalDate.of(adjusted.getYear() - 1, 12, 31)};
            default -> throw badRequest("不支持的核算周期类型");
        };
    }

    private LocalDate[] previousQuarter(LocalDate date) {
        int currentQuarterStart = ((date.getMonthValue() - 1) / 3) * 3 + 1;
        LocalDate start = date.withMonth(currentQuarterStart).withDayOfMonth(1).minusMonths(3);
        return new LocalDate[]{start, start.plusMonths(3).minusDays(1)};
    }

    private JsonNode validateArray(JsonNode config, String field, int min, int max) {
        JsonNode values = config.get(field);
        if (values == null || !values.isArray() || values.isEmpty()) {
            throw badRequest(field + "不能为空");
        }
        for (JsonNode value : values) {
            if (!value.isIntegralNumber() || value.asInt() < min || value.asInt() > max) {
                throw badRequest(field + "存在超出范围的值");
            }
        }
        return values;
    }

    private String requiredText(JsonNode config, String field) {
        JsonNode value = config.get(field);
        if (value == null || !value.isTextual() || value.asText().isBlank()) {
            throw badRequest(field + "不能为空");
        }
        return value.asText().trim();
    }

    private LocalDate optionalDate(JsonNode config, String field) {
        JsonNode node = config.get(field);
        if (node == null || node.isNull()) {
            return null;
        }
        if (!node.isTextual()) {
            throw badRequest(field + "必须使用ISO日期格式");
        }
        String value = node.asText().trim();
        if (value.isEmpty()) {
            return null;
        }
        try {
            return LocalDate.parse(value.length() >= 10 ? value.substring(0, 10) : value);
        } catch (DateTimeParseException ex) {
            throw badRequest(field + "必须使用ISO日期格式");
        }
    }

    private int optionalInt(JsonNode config, String field, int defaultValue) {
        JsonNode value = config.get(field);
        if (value == null || value.isNull()) {
            return defaultValue;
        }
        if (!value.isIntegralNumber()) {
            throw badRequest(field + "必须为整数");
        }
        return value.asInt();
    }

    private ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }
}
