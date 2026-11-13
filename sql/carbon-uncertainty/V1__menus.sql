-- Uncertainty analysis module menu and permission. Idempotent and safe for existing data.
SET NAMES utf8mb4;

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '碳排放报告不确定性分析',2000,11,'uncertainty','carbon/uncertainty/index','','CarbonUncertainty',1,0,'C','0','0','carbon:uncertainty:view','data-analysis','admin',NOW(),'',NULL,'碳排放报告不确定性分析'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:uncertainty:view');

INSERT INTO sys_role_menu (role_id,menu_id)
SELECT r.role_id,m.menu_id FROM sys_role r
JOIN sys_menu m ON m.perms='carbon:uncertainty:view'
LEFT JOIN sys_role_menu rm ON rm.role_id=r.role_id AND rm.menu_id=m.menu_id
WHERE r.role_key IN ('admin','company_admin') AND rm.role_id IS NULL;
