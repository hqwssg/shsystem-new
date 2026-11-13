-- Read only. Display all three required roles, including missing ones.
SET NAMES utf8mb4;
SELECT d.dept_id,d.dept_name,r.role,f.id,f.original_name,f.report_id,f.size_bytes,
 OCTET_LENGTH(f.content) AS content_bytes,
 CASE WHEN f.id IS NULL THEN 'MISSING'
      WHEN COALESCE(OCTET_LENGTH(f.content),0)=0 AND NULLIF(TRIM(f.object_key),'') IS NOT NULL THEN 'EXTERNAL_REFERENCE_CHECK'
      WHEN COALESCE(OCTET_LENGTH(f.content),0)=0 THEN 'EMPTY_CONTENT'
      WHEN f.report_id IS NOT NULL THEN 'WRONG_REPORT_BINDING'
      WHEN f.size_bytes IS NULL OR f.size_bytes<>OCTET_LENGTH(f.content) THEN 'SIZE_MISMATCH'
      WHEN f.sha256 IS NULL OR LOWER(TRIM(f.sha256))<>SHA2(f.content,256) THEN 'HASH_MISMATCH'
      ELSE 'CONTENT_OK' END AS image_check
FROM sys_dept d CROSS JOIN (
 SELECT 'cover_logo' AS role UNION ALL SELECT 'org_chart' UNION ALL SELECT 'office_location'
) r LEFT JOIN report_file f ON f.dept_id=d.dept_id AND f.kind='default' AND f.role=r.role
WHERE d.dept_name IN ('肃宁分公司','原平分公司','机辆分公司') AND d.status='0' AND d.del_flag='0'
ORDER BY d.dept_name,r.role,f.id;
