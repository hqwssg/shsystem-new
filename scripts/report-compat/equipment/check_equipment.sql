SET NAMES utf8mb4;
SELECT d.dept_id,d.dept_name,p.entity_code,
       JSON_LENGTH(p.default_equipment_json) AS equipment_rows,
       p.version,p.update_by,p.update_time
FROM sys_dept d
JOIN sys_carbon_company c ON c.dept_id=d.dept_id
LEFT JOIN report_dept_profile p ON p.dept_id=d.dept_id
WHERE d.dept_name IN ('肃宁分公司','原平分公司','机辆分公司')
  AND d.status='0' AND d.del_flag='0'
ORDER BY d.dept_id;

SELECT d.dept_name,j.name,j.model,j.quantity,j.energy_type,j.remark
FROM report_dept_profile p
JOIN sys_dept d ON d.dept_id=p.dept_id
JOIN sys_carbon_company c ON c.dept_id=d.dept_id
JOIN JSON_TABLE(p.default_equipment_json,'$[*]' COLUMNS(
    source_row FOR ORDINALITY,
    name VARCHAR(255) PATH '$.name',
    model VARCHAR(128) PATH '$.model',
    quantity DECIMAL(18,4) PATH '$.quantity' NULL ON EMPTY NULL ON ERROR,
    energy_type VARCHAR(64) PATH '$.energy_type',
    remark VARCHAR(255) PATH '$.remark'
)) AS j ON TRUE
WHERE d.dept_name IN ('肃宁分公司','原平分公司','机辆分公司')
  AND d.status='0' AND d.del_flag='0'
ORDER BY d.dept_id,j.source_row;
