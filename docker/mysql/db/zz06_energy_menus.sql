-- Energy module menus.
-- AUTO_INCREMENT IDs avoid collisions with menus created by previous releases.
-- Permission keys make this migration safe to run repeatedly.
SET NAMES utf8mb4;

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '重空协同与能量优化',2000,11,'energy','carbon/energy/index','','',1,0,'C','0','0','carbon:energy:list','chart','admin',NOW(),'',NULL,'能量回收调度任务列表'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:list');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '任务查询',m.menu_id,1,'','','','',1,0,'F','0','0','carbon:energy:query','#','admin',NOW(),'',NULL,'查询能量任务'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:query');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '发布数据版本',m.menu_id,2,'','','','',1,0,'F','0','0','carbon:energy:version','#','admin',NOW(),'',NULL,'发布不可变输入版本'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:version');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '提交任务',m.menu_id,3,'','','','',1,0,'F','0','0','carbon:energy:run','#','admin',NOW(),'',NULL,'创建算法任务'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:run');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '取消任务',m.menu_id,4,'','','','',1,0,'F','0','0','carbon:energy:cancel','#','admin',NOW(),'',NULL,'取消非终态任务'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:cancel');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '下载工件',m.menu_id,5,'','','','',1,0,'F','0','0','carbon:energy:download','#','admin',NOW(),'',NULL,'下载结果工件'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:download');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目对照',m.menu_id,6,'','','','',1,0,'F','0','0','carbon:energy:project','#','admin',NOW(),'',NULL,'维护部门与项目对照'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:project');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '删除任务',m.menu_id,7,'','','','',1,0,'F','0','0','carbon:energy:remove','#','admin',NOW(),'',NULL,'删除任意状态任务'
FROM sys_menu m WHERE m.perms='carbon:energy:list' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:energy:remove');

INSERT INTO sys_role_menu (role_id,menu_id)
SELECT r.role_id,m.menu_id FROM sys_role r
JOIN sys_menu m ON m.perms IN ('carbon:energy:list','carbon:energy:query','carbon:energy:version','carbon:energy:run','carbon:energy:cancel','carbon:energy:download','carbon:energy:project','carbon:energy:remove')
LEFT JOIN sys_role_menu rm ON rm.role_id=r.role_id AND rm.menu_id=m.menu_id
WHERE r.role_key IN ('admin', 'company_admin') AND rm.role_id IS NULL;
