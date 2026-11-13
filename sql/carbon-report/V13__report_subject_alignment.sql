-- Correct department/report boundary mappings created by older V11 releases.
-- Only departments with their own BRANCH calculation node are enabled.
SET NAMES utf8mb4;
USE carbon_emissions;

UPDATE report_dept_subject
SET subject_node_id = NULL,
    enabled = '0',
    update_by = 'admin',
    update_time = NOW();

INSERT INTO report_dept_subject
    (dept_id, subject_node_id, energy_allocation, enabled, create_by, create_time)
SELECT d.dept_id,
       (
         SELECT n.id
         FROM emission_node n
         INNER JOIN emission_node_info ni ON ni.node_id = n.id
         WHERE ni.node_category = 'BRANCH'
           AND (n.name = d.dept_name OR n.name LIKE CONCAT(d.dept_name, '-%'))
         ORDER BY ni.include_in_calculation DESC, n.id
         LIMIT 1
       ),
       CASE d.dept_name
         WHEN '原平分公司' THEN 'yuanping'
         WHEN '肃宁分公司' THEN 'suring'
         WHEN '机辆分公司' THEN 'jilong'
       END,
       IF(EXISTS (
         SELECT 1
         FROM emission_node n
         INNER JOIN emission_node_info ni ON ni.node_id = n.id
         WHERE ni.node_category = 'BRANCH'
           AND (n.name = d.dept_name OR n.name LIKE CONCAT(d.dept_name, '-%'))
       ), '1', '0'),
       'admin', NOW()
FROM sys_dept d
WHERE d.status = '0' AND d.del_flag = '0'
  AND d.dept_name IN ('原平分公司', '肃宁分公司', '机辆分公司')
ON DUPLICATE KEY UPDATE
    subject_node_id = VALUES(subject_node_id),
    energy_allocation = VALUES(energy_allocation),
    enabled = VALUES(enabled),
    update_by = 'admin',
    update_time = NOW();
