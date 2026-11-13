package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.service.EmissionDataFreshnessService;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/** Database-backed data lineage shared by the model and report modules. */
@Service
public class EmissionDataFreshnessServiceImpl implements EmissionDataFreshnessService {
    private static volatile boolean initialized;
    private final JdbcTemplate jdbc;

    public EmissionDataFreshnessServiceImpl(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void initializeSchema() {
        ensureTables();
    }

    @Override
    public long currentRevision(Long templateId) {
        ensureTables();
        Long value = jdbc.query("select data_revision from emission_data_freshness where template_id=?",
                rs -> rs.next() ? rs.getLong(1) : 0L, templateId);
        return value == null ? 0L : value;
    }

    @Override
    public boolean needsRecalculation(Long templateId) {
        ensureTables();
        Boolean value = jdbc.query("select needs_recalculation from emission_data_freshness where template_id=?",
                rs -> rs.next() && rs.getBoolean(1), templateId);
        return Boolean.TRUE.equals(value);
    }

    @Override
    public int markCollectionPointChanged(Integer collectionPointType, Long collectionPointId, String reason) {
        ensureTables();
        String sql = "insert into emission_data_freshness(template_id,data_revision,changed_at,needs_recalculation,last_reason) "
                + "select distinct n.template_id,1,current_timestamp,1,? from emission_node n "
                + "join emission_node_config c on c.node_id=n.id "
                + "where c.collection_point_type=? and c.collection_point_id=? "
                + "on duplicate key update data_revision=data_revision+1,changed_at=current_timestamp,"
                + "needs_recalculation=1,last_reason=values(last_reason)";
        return jdbc.update(sql, reason == null ? "采集数据审核通过" : reason, collectionPointType, collectionPointId);
    }

    @Override
    public long captureCalculation(Long calculationTemplateId, Long templateId) {
        ensureTables();
        long revision = currentRevision(templateId);
        jdbc.update("insert into emission_calculation_data_state(calculation_template_id,template_id,data_revision,captured_at) "
                        + "values(?,?,?,current_timestamp) on duplicate key update data_revision=values(data_revision),captured_at=current_timestamp",
                calculationTemplateId, templateId, revision);
        return revision;
    }

    @Override
    public void completeCalculation(Long calculationTemplateId, Long templateId, long revision) {
        ensureTables();
        jdbc.update("update emission_data_freshness set needs_recalculation=0 "
                        + "where template_id=? and data_revision=?", templateId, revision);
    }

    private synchronized void ensureTables() {
        if (initialized) return;
        try { jdbc.execute("alter table emission_calculation_template add column data_revision bigint not null default 0"); } catch (RuntimeException ignored) { }
        try { jdbc.execute("alter table emission_calculation_template drop index uk_template_cycle"); } catch (RuntimeException ignored) { }
        // A voided result must be followed by a new run for the same cycle.
        // Do not recreate the old database-wide unique key; concurrency is
        // serialized by CalculationTaskReservationService instead.
        try { jdbc.execute("alter table emission_calculation_template drop index uk_template_cycle_revision"); } catch (RuntimeException ignored) { }
        try {
            jdbc.execute("update emission_calculation_template ct join ("
                    + "select dup.id from emission_calculation_template dup join ("
                    + "select template_id,calculation_cycle_start_date,calculation_cycle_end_date,min(id) keep_id "
                    + "from emission_calculation_template group by template_id,calculation_cycle_start_date,calculation_cycle_end_date"
                    + ") grouped on grouped.template_id=dup.template_id "
                    + "and grouped.calculation_cycle_start_date=dup.calculation_cycle_start_date "
                    + "and grouped.calculation_cycle_end_date=dup.calculation_cycle_end_date "
                    + "where dup.id<>grouped.keep_id and dup.data_revision=0"
                    + ") old_duplicate on old_duplicate.id=ct.id set ct.data_revision=-ct.id");
        } catch (RuntimeException ignored) { }
        jdbc.execute("create table if not exists emission_data_freshness ("
                + "template_id bigint primary key,data_revision bigint not null default 0,"
                + "changed_at timestamp null,needs_recalculation boolean not null default false,"
                + "last_reason varchar(255) null) engine=InnoDB default charset=utf8mb4");
        jdbc.execute("create table if not exists emission_calculation_data_state ("
                + "calculation_template_id bigint primary key,template_id bigint not null,"
                + "data_revision bigint not null default 0,captured_at timestamp not null default current_timestamp,"
                + "index idx_calc_data_state_template(template_id)) engine=InnoDB default charset=utf8mb4");
        initialized = true;
    }
}
