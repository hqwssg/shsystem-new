-- Read-only: confirm these rows before executing V1/V2. Never replace an existing menu ID.
SELECT menu_id,menu_name,parent_id,path,perms FROM sys_menu
WHERE menu_id=2000 OR menu_id BETWEEN 2110 AND 2115 OR perms LIKE 'carbon:singleTrain:%';
SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()
AND (TABLE_NAME LIKE 'energy\_%' OR TABLE_NAME LIKE 'single\_%');
SELECT p.project_code,v.version_code,v.version_id,v.lifecycle_status
FROM energy_project p JOIN energy_project_version v USING(project_id)
WHERE p.project_code='shuohuang_demo' AND v.version_code='v1';
