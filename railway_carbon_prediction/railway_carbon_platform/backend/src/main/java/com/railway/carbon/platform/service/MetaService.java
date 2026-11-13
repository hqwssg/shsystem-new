package com.railway.carbon.platform.service;

import com.railway.carbon.platform.dto.Dtos;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class MetaService {

    private final JdbcTemplate jdbc;

    public MetaService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<Dtos.Org> orgs() {
        return jdbc.query("""
                SELECT org_id, org_name, org_level, province
                FROM prediction_org
                WHERE status = 'active'
                ORDER BY org_level, org_id
                """, (rs, i) -> new Dtos.Org(
                rs.getString("org_id"), rs.getString("org_name"),
                rs.getInt("org_level"), rs.getString("province")));
    }

    public List<Dtos.Var> vars() {
        return jdbc.query("""
                SELECT var_id, var_name, unit, var_category, is_traction, is_target, sort_order
                FROM prediction_energy_var
                ORDER BY sort_order
                """, (rs, i) -> new Dtos.Var(
                rs.getString("var_id"), rs.getString("var_name"), rs.getString("unit"),
                rs.getString("var_category"), rs.getBoolean("is_traction"),
                rs.getBoolean("is_target"), rs.getInt("sort_order")));
    }
}
