-- Prevent run deletion from failing when its selected optimization candidate is cascaded.
SET @schema_name = DATABASE();

SET @has_constraint = (
    SELECT COUNT(*)
    FROM information_schema.REFERENTIAL_CONSTRAINTS
    WHERE BINARY CONSTRAINT_SCHEMA = BINARY @schema_name
      AND BINARY TABLE_NAME = BINARY 'energy_optimization_decision'
      AND BINARY CONSTRAINT_NAME = BINARY 'fk_energy_decision_candidate'
);

SET @drop_sql = IF(
    @has_constraint > 0,
    'ALTER TABLE energy_optimization_decision DROP FOREIGN KEY fk_energy_decision_candidate',
    'SELECT 1'
);
PREPARE drop_statement FROM @drop_sql;
EXECUTE drop_statement;
DEALLOCATE PREPARE drop_statement;

-- Existing deployments may have different CHAR collations on these legacy
-- tables. A string foreign key is legal only when both columns match exactly;
-- skip the optional constraint when they do not, while retaining the delete
-- behavior in the application layer.
SET @candidate_fk_compatible = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS child_col
    JOIN information_schema.COLUMNS parent_col
      ON BINARY parent_col.TABLE_SCHEMA = BINARY child_col.TABLE_SCHEMA
     AND BINARY parent_col.COLUMN_NAME = BINARY 'candidate_id'
    WHERE BINARY child_col.TABLE_SCHEMA = BINARY @schema_name
      AND BINARY child_col.TABLE_NAME = BINARY 'energy_optimization_decision'
      AND BINARY child_col.COLUMN_NAME = BINARY 'selected_candidate_id'
      AND BINARY parent_col.TABLE_NAME = BINARY 'energy_optimization_candidate'
      AND BINARY COALESCE(child_col.COLUMN_TYPE, '') = BINARY COALESCE(parent_col.COLUMN_TYPE, '')
      AND BINARY COALESCE(child_col.CHARACTER_SET_NAME, '') = BINARY COALESCE(parent_col.CHARACTER_SET_NAME, '')
      AND BINARY COALESCE(child_col.COLLATION_NAME, '') = BINARY COALESCE(parent_col.COLLATION_NAME, '')
);

SET @add_sql = IF(
    @candidate_fk_compatible > 0,
    'ALTER TABLE energy_optimization_decision ADD CONSTRAINT fk_energy_decision_candidate FOREIGN KEY (selected_candidate_id) REFERENCES energy_optimization_candidate(candidate_id) ON DELETE SET NULL',
    'SELECT 1'
);
PREPARE add_statement FROM @add_sql;
EXECUTE add_statement;
DEALLOCATE PREPARE add_statement;
