-- Approved collection data and calculation/report snapshots share an explicit revision.
SET @db := DATABASE();
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_calculation_template' AND column_name='data_revision')=0,
  'ALTER TABLE emission_calculation_template ADD COLUMN data_revision BIGINT NOT NULL DEFAULT 0 COMMENT ''approved collection data revision'' AFTER status', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=@db AND table_name='emission_calculation_template' AND index_name='uk_template_cycle')>0,
  'ALTER TABLE emission_calculation_template DROP INDEX uk_template_cycle', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
-- Preserve duplicate historical runs from old installations without deleting them.
UPDATE emission_calculation_template ct
JOIN (
  SELECT dup.id
  FROM emission_calculation_template dup
  JOIN (
    SELECT template_id, calculation_cycle_start_date, calculation_cycle_end_date, MIN(id) AS keep_id
    FROM emission_calculation_template
    GROUP BY template_id, calculation_cycle_start_date, calculation_cycle_end_date
  ) grouped ON grouped.template_id = dup.template_id
    AND grouped.calculation_cycle_start_date = dup.calculation_cycle_start_date
    AND grouped.calculation_cycle_end_date = dup.calculation_cycle_end_date
  WHERE dup.id <> grouped.keep_id AND dup.data_revision = 0
) old_duplicate ON old_duplicate.id = ct.id
SET ct.data_revision = -ct.id;
-- Do not recreate the historical global unique index here. It was removed by
-- schema-update-20261021-calculation-void.sql because production databases
-- legitimately contain duplicate historical cycles and the reservation
-- service now serializes active runs. Creating it before the later removal
-- would fail on those databases and stop the whole deployment.
CREATE TABLE IF NOT EXISTS emission_data_freshness (
  template_id BIGINT PRIMARY KEY, data_revision BIGINT NOT NULL DEFAULT 0,
  changed_at TIMESTAMP NULL, needs_recalculation BOOLEAN NOT NULL DEFAULT FALSE,
  last_reason VARCHAR(255) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS emission_calculation_data_state (
  calculation_template_id BIGINT PRIMARY KEY, template_id BIGINT NOT NULL,
  data_revision BIGINT NOT NULL DEFAULT 0, captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_calc_data_state_template(template_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
