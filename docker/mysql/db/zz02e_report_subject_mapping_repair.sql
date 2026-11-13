-- Repair report subject mappings for the company root and older installations.
-- The administrator is normally assigned to the company root department (3000),
-- while earlier migrations only mapped the three branch departments.  Keep
-- existing explicit mappings unchanged and fill only missing subject nodes.
SET NAMES utf8mb4;
USE carbon_emissions;

SET @fallback_subject_node_id := COALESCE(
    (SELECT n.id
       FROM emission_node n
       INNER JOIN emission_node_info ni ON ni.node_id = n.id
      WHERE ni.node_category = 'BRANCH'
        AND COALESCE(ni.include_in_calculation, 1) = 1
      ORDER BY n.id
      LIMIT 1),
    (SELECT n.id
       FROM emission_node n
      WHERE n.parent_id IS NULL
      ORDER BY n.id
      LIMIT 1)
);

SET @fallback_energy_allocation := COALESCE(
    (SELECT CASE
              WHEN n.name LIKE '肃宁分公司%' THEN 'suring'
              WHEN n.name LIKE '原平分公司%' THEN 'yuanping'
              WHEN n.name LIKE '机辆分公司%' THEN 'jilong'
              ELSE NULL
            END
       FROM emission_node n
      WHERE n.id = @fallback_subject_node_id
      LIMIT 1),
    'suring'
);

-- First repair rows whose department name has an exact branch-node match.
UPDATE report_dept_subject s
INNER JOIN sys_dept d ON d.dept_id = s.dept_id
INNER JOIN emission_node n
        ON (n.name = d.dept_name OR n.name LIKE CONCAT(d.dept_name, '-%'))
INNER JOIN emission_node_info ni ON ni.node_id = n.id
SET s.subject_node_id = n.id,
    s.energy_allocation = CASE
      WHEN d.dept_name LIKE '肃宁分公司%' THEN 'suring'
      WHEN d.dept_name LIKE '原平分公司%' THEN 'yuanping'
      WHEN d.dept_name LIKE '机辆分公司%' THEN 'jilong'
      ELSE s.energy_allocation
    END,
    s.enabled = '1',
    s.update_by = 'admin',
    s.update_time = NOW()
WHERE s.subject_node_id IS NULL
  AND ni.node_category = 'BRANCH';

-- The company root is the default department of the built-in administrator.
-- Bind it only when no explicit mapping exists, preserving user configuration.
UPDATE report_dept_subject s
INNER JOIN sys_dept d ON d.dept_id = s.dept_id
SET s.subject_node_id = @fallback_subject_node_id,
    s.energy_allocation = @fallback_energy_allocation,
    s.enabled = '1',
    s.update_by = 'admin',
    s.update_time = NOW()
WHERE d.parent_id = 0
  AND s.subject_node_id IS NULL
  AND @fallback_subject_node_id IS NOT NULL;

INSERT INTO report_dept_subject
    (dept_id, subject_node_id, energy_allocation, enabled, create_by, create_time)
SELECT d.dept_id, @fallback_subject_node_id, @fallback_energy_allocation,
       '1', 'admin', NOW()
FROM sys_dept d
WHERE d.parent_id = 0
  AND @fallback_subject_node_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM report_dept_subject s WHERE s.dept_id = d.dept_id
  );
