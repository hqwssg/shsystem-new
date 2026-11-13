-- Repair collection record billing-cycle columns and legacy rows.
-- Safe to run repeatedly on existing MySQL/MariaDB installations.
SET NAMES utf8mb4;
SET @db := DATABASE();

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema=@db AND table_name='emission_collection_record'
                  AND column_name='billing_cycle_start_date')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN billing_cycle_start_date DATE NULL COMMENT ''measurement cycle start''',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema=@db AND table_name='emission_collection_record'
                  AND column_name='billing_cycle_end_date')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN billing_cycle_end_date DATE NULL COMMENT ''measurement cycle end''',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Preserve exact dates for cumulative meters. For periodic meters, historical
-- readings represent the calendar month containing collection_time.
UPDATE emission_collection_record r
LEFT JOIN emission_meter_info em
  ON r.collection_point_type = 1 AND em.id = r.collection_point_id
LEFT JOIN emission_fossil_fuel_meter_info ef
  ON r.collection_point_type = 2 AND ef.id = r.collection_point_id
LEFT JOIN emission_purchased_heat_meter_info eh
  ON r.collection_point_type = 3 AND eh.id = r.collection_point_id
SET r.billing_cycle_start_date = CASE
      WHEN COALESCE(em.is_cumulative, ef.is_cumulative, eh.is_cumulative, r.is_cumulative, 0) = 1
        THEN DATE(r.collection_time)
      ELSE DATE_FORMAT(r.collection_time, '%Y-%m-01')
    END,
    r.billing_cycle_end_date = CASE
      WHEN COALESCE(em.is_cumulative, ef.is_cumulative, eh.is_cumulative, r.is_cumulative, 0) = 1
        THEN DATE(r.collection_time)
      ELSE LAST_DAY(r.collection_time)
    END
WHERE r.collection_time IS NOT NULL
  AND (r.billing_cycle_start_date IS NULL OR r.billing_cycle_end_date IS NULL)
  AND r.reading_value IS NOT NULL
  AND r.collection_status = 1;
