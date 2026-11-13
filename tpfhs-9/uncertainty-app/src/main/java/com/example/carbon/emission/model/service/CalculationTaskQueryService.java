package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.CalculationTaskOption;
import com.example.carbon.emission.model.security.UncertaintySecurityContext;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.List;

@Service
public class CalculationTaskQueryService {
    private final NamedParameterJdbcTemplate jdbc;

    public CalculationTaskQueryService(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<CalculationTaskOption> findSuccessful(String templateName, String companyName, Integer year,
            UncertaintySecurityContext context) {
        StringBuilder sql = new StringBuilder("""
                SELECT c.id AS task_id, c.template_id, t.name AS template_name,
                       c.company_dept_id, d.dept_name AS company_name,
                       c.calculation_cycle_start_date, c.calculation_cycle_end_date,
                       c.status, c.calculation_end_time
                  FROM emission_calculation_template c
                  JOIN emission_template t ON t.id = c.template_id
             LEFT JOIN sys_dept d ON d.dept_id = c.company_dept_id
                 WHERE c.status = 2
                """);
        MapSqlParameterSource params = new MapSqlParameterSource();
        if (templateName != null && !templateName.isBlank()) {
            sql.append(" AND t.name LIKE :templateName");
            params.addValue("templateName", "%" + templateName.trim() + "%");
        }
        if (companyName != null && !companyName.isBlank()) {
            sql.append(" AND d.dept_name LIKE :companyName");
            params.addValue("companyName", "%" + companyName.trim() + "%");
        }
        if (year != null) {
            sql.append(" AND YEAR(c.calculation_cycle_start_date) = :year");
            params.addValue("year", year);
        }
        if (context != null && !context.allData()) {
            if (context.selfOnly() && context.userId() != null) {
                sql.append(" AND c.created_by = :userId");
                params.addValue("userId", context.userId());
            } else if (!context.effectiveDeptIds().isEmpty()) {
                sql.append(" AND (c.company_dept_id IN (:deptIds) OR (c.company_dept_id IS NULL AND t.dept_id IN (:deptIds)))");
                params.addValue("deptIds", context.effectiveDeptIds());
            } else {
                sql.append(" AND 1 = 0");
            }
        }
        sql.append(" ORDER BY c.calculation_end_time DESC, c.id DESC LIMIT 500");
        return jdbc.query(sql.toString(), params, (rs, rowNum) -> new CalculationTaskOption(
                rs.getLong("task_id"), rs.getLong("template_id"), rs.getString("template_name"),
                (Long) rs.getObject("company_dept_id"), rs.getString("company_name"),
                rs.getObject("calculation_cycle_start_date", LocalDate.class),
                rs.getObject("calculation_cycle_end_date", LocalDate.class), rs.getInt("status"),
                rs.getTimestamp("calculation_end_time") == null ? null : rs.getTimestamp("calculation_end_time").toLocalDateTime()));
    }
}
