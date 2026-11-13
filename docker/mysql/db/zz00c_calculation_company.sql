-- Additive and repeatable. Existing tasks stay unconfirmed; no automatic backfill.
SET NAMES utf8mb4;
SET @company_schema := DATABASE();
SET @company_sql := IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@company_schema
   AND table_name='emission_calculation_template' AND column_name='company_dept_id')=0,
  'ALTER TABLE emission_calculation_template ADD COLUMN company_dept_id BIGINT NULL COMMENT ''核算业务公司归属快照，NULL为历史未确认''',
  'SELECT 1');
PREPARE company_stmt FROM @company_sql;
EXECUTE company_stmt;
DEALLOCATE PREPARE company_stmt;
SET @company_sql := IF(
  (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=@company_schema
   AND table_name='emission_calculation_template' AND index_name='idx_calc_company_period')=0,
  'ALTER TABLE emission_calculation_template ADD INDEX idx_calc_company_period (company_dept_id,status,calculation_cycle_start_date,calculation_cycle_end_date)',
  'SELECT 1');
PREPARE company_stmt FROM @company_sql;
EXECUTE company_stmt;
DEALLOCATE PREPARE company_stmt;
