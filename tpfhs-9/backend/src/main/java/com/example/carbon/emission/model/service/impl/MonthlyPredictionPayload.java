package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.service.UnitConversionService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.*;

@Component
class MonthlyPredictionPayload {
    private static final Set<String> ORGANIZATIONS = Set.of("JLG", "SNF", "YPF");
    private final JdbcTemplate jdbc;
    private final UnitConversionService units;
    private final Set<String> traction;
    private final Set<String> auxiliary;

    MonthlyPredictionPayload(JdbcTemplate jdbc, UnitConversionService units,
            @Value("${carbon.statistics.prediction-send.jlg-traction-categories:}") String traction,
            @Value("${carbon.statistics.prediction-send.jlg-auxiliary-categories:}") String auxiliary) {
        this.jdbc = jdbc;
        this.units = units;
        this.traction = categories(traction);
        this.auxiliary = categories(auxiliary);
    }

    Map<String, Object> build(MonthlyPredictionOutbox.Delivery job) {
        String org = jdbc.query("select org_id from prediction_org where platform_dept_id=? and status='active'",
                rs -> rs.next() ? rs.getString(1) : "", job.company());
        if (!ORGANIZATIONS.contains(org)) throw new IllegalArgumentException("分公司未配置预测组织映射");
        var values = new TreeMap<String, BigDecimal>();
        var missing = new TreeSet<String>();
        var affected = new TreeSet<String>();
        for (var point : job.snapshot().missing()) {
            missing.add("point:" + point.type() + ":" + point.id() + ":" + point.status());
            if (point.noValue()) affected.add(point.category() + "/" + point.subcategory());
        }
        var heatSources = new ArrayList<Map<String, Object>>();
        for (var group : job.snapshot().groups()) {
            String variable = variable(org, group);
            if (affected.contains(group.category() + "/" + group.subcategory())) {
                // A group with a missing member is not a verified zero or a complete amount.
                missing.add("missing:" + variable);
                continue;
            }
            if ("HEAT_REPORTED".equals(variable)) {
                if ("PH_HA".equals(group.subcategory()) && "m2".equals(group.unit())) {
                    // The receiver derives both GJ values from the area and its approved effective rules.
                    heatSources.add(Map.of("kind", "area", "amount", group.value()));
                } else {
                    try {
                        BigDecimal amount = units.convertRequired(group.subcategory(), group.unit(), "GJ", group.value());
                        heatSources.add(Map.of("kind", "measured", "amount", amount));
                        values.merge(variable, amount, BigDecimal::add);
                    } catch (IllegalArgumentException | IllegalStateException error) {
                        missing.add("unmapped_heat:" + group.subcategory());
                    }
                }
                continue;
            }
            String unit = switch (variable) {
                case "GAS" -> "wan_m3";
                case "DIESEL", "GASOLINE" -> "t";
                default -> "MWh";
            };
            try {
                values.merge(variable, units.convertRequired(group.subcategory(), group.unit(), unit, group.value()),
                        BigDecimal::add);
            } catch (IllegalArgumentException | IllegalStateException error) {
                missing.add("unit:" + variable);
            }
        }
        if ("JLG".equals(org)) {
            BigDecimal trac = values.get("ELEC_TRAC");
            BigDecimal aux = values.get("ELEC_AUX");
            if (trac != null && aux != null && missing.stream().noneMatch(s -> s.endsWith(":ELEC_TRAC")
                    || s.endsWith(":ELEC_AUX"))) {
                values.put("ELEC_TOTAL", trac.setScale(6, RoundingMode.HALF_UP)
                        .add(aux.setScale(6, RoundingMode.HALF_UP)));
            } else {
                missing.add("missing:ELEC_TRIPLE");
            }
        }
        if (heatSources.stream().anyMatch(source -> "area".equals(source.get("kind")))) {
            values.remove("HEAT_REPORTED"); // Only the receiver can produce the complete GJ total.
        }
        String period = job.month().toString();
        List<Map<String, Object>> records = values.entrySet().stream().map(entry -> {
            String var = entry.getKey();
            String unit = switch (var) {
                case "HEAT_REPORTED" -> "GJ";
                case "GAS" -> "万立方米";
                case "DIESEL", "GASOLINE" -> "吨";
                default -> "MWh";
            };
            return Map.<String, Object>of("org_id", org, "period", period, "var_id", var,
                    "value", entry.getValue().setScale(6, RoundingMode.HALF_UP), "unit", unit);
        }).toList();
        return Map.of("idempotency_key", "carbon-month-" + job.id(), "operator", "carbon-monthly",
                "run_anomaly", true, "records", records, "source_snapshot",
                Map.of("version", job.id(), "org_id", org, "period", period, "operation_type", job.type(),
                        "complete", job.snapshot().complete() && missing.isEmpty(), "missing", missing,
                        "heat_sources", heatSources));
    }

    private String variable(String org, MonthlyPredictionOutbox.Group group) {
        return switch (group.subcategory()) {
            case "FF_D" -> "DIESEL";
            case "FF_G" -> "GASOLINE";
            case "FF_NG" -> "GAS";
            case "PH_HD", "PH_HA", "PH_HW", "PH_HS" -> "HEAT_REPORTED";
            case "PE_PF" -> {
                if (!"JLG".equals(org)) yield "ELEC_TOTAL";
                if (traction.contains(group.category()) && !auxiliary.contains(group.category())) yield "ELEC_TRAC";
                if (auxiliary.contains(group.category()) && !traction.contains(group.category())) yield "ELEC_AUX";
                throw new IllegalArgumentException("机辆电力分组尚未确认：" + group.category());
            }
            default -> throw new IllegalArgumentException("未配置预测品种映射：" + group.subcategory());
        };
    }

    private static Set<String> categories(String value) {
        return new HashSet<>(Arrays.stream(value.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList());
    }
}
