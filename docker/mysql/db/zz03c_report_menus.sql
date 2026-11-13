-- Report module menus.
-- Use permission keys and AUTO_INCREMENT IDs so upgrades never collide with
-- IDs allocated by another module.
SET NAMES utf8mb4;

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '碳排放报告',2000,10,'report','carbon/report/index','','',1,0,'C','0','0','carbon:report:list','documentation','admin',NOW(),'',NULL,'碳排放报告列表'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:list');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告查询',m.menu_id,1,'','','','',1,0,'F','0','0','carbon:report:query','#','admin',NOW(),'',NULL,'查询报告'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:query');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告新增',m.menu_id,2,'','','','',1,0,'F','0','0','carbon:report:add','#','admin',NOW(),'',NULL,'新增报告'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:add');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告修改',m.menu_id,3,'','','','',1,0,'F','0','0','carbon:report:edit','#','admin',NOW(),'',NULL,'修改报告'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:edit');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告删除',m.menu_id,4,'','','','',1,0,'F','0','0','carbon:report:remove','#','admin',NOW(),'',NULL,'删除报告'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:remove');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告导入',m.menu_id,5,'','','','',1,0,'F','0','0','carbon:report:import','#','admin',NOW(),'',NULL,'导入活动数据'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:import');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告校验',m.menu_id,6,'','','','',1,0,'F','0','0','carbon:report:validate','#','admin',NOW(),'',NULL,'校验报告'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:validate');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告生成',m.menu_id,7,'','','','',1,0,'F','0','0','carbon:report:generate','#','admin',NOW(),'',NULL,'生成Word/PDF'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:generate');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '报告下载',m.menu_id,8,'','','','',1,0,'F','0','0','carbon:report:download','#','admin',NOW(),'',NULL,'下载生成文件'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:download');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '企业档案查询',m.menu_id,9,'','','','',1,0,'F','0','0','carbon:report:profile:query','#','admin',NOW(),'',NULL,'查询企业档案'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:profile:query');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '企业档案编辑',m.menu_id,10,'','','','',1,0,'F','0','0','carbon:report:profile:edit','#','admin',NOW(),'',NULL,'编辑企业档案'
FROM sys_menu m WHERE m.perms='carbon:report:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:report:profile:edit');

INSERT INTO sys_role_menu (role_id,menu_id)
SELECT r.role_id,m.menu_id FROM sys_role r
JOIN sys_menu m ON m.perms IN ('carbon:report:list','carbon:report:query','carbon:report:add','carbon:report:edit','carbon:report:remove','carbon:report:import','carbon:report:validate','carbon:report:generate','carbon:report:download','carbon:report:profile:query','carbon:report:profile:edit')
LEFT JOIN sys_role_menu rm ON rm.role_id=r.role_id AND rm.menu_id=m.menu_id
WHERE r.role_key IN ('admin', 'company_admin') AND rm.role_id IS NULL;
