-- Optional reversible visibility rollback only. No task/version/result is deleted.
-- Set the dept_id printed by init before running this in a fresh connection.
-- SET @algorithm_seed_dept_id=your_actual_dept_id;
START TRANSACTION;
UPDATE energy_dept_project SET enabled='0' WHERE project_code=CONVERT(0x616c676f726974686d5f64656d6f5f3230323631313130 USING utf8mb4) AND dept_id=@algorithm_seed_dept_id;
UPDATE single_dept_project SET enabled=0 WHERE project_code=CONVERT(0x616c676f726974686d5f64656d6f5f3230323631313130 USING utf8mb4) AND dept_id=@algorithm_seed_dept_id;
COMMIT;
-- To restore visibility, deliberately set enabled back to 1 for these same two bindings.
