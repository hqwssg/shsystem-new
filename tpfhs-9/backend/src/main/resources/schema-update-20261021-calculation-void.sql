-- Allow a voided calculation run to be followed by a new run for the same cycle.
-- The reservation service serializes runs by locking the source template and
-- rejects pending/running/successful rows, so the old database-wide unique key
-- is no longer needed and would block the new run after a void operation.
SET @db := DATABASE();
SET @sql := IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema=@db AND table_name='emission_calculation_template'
     AND index_name='uk_template_cycle_revision') > 0,
  'ALTER TABLE emission_calculation_template DROP INDEX uk_template_cycle_revision',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
