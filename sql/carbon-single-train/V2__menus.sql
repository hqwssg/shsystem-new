-- Dedicated permissions. Grant operational permissions separately from version maintenance.
INSERT INTO sys_menu(menu_id,menu_name,parent_id,order_num,path,component,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time)
SELECT 2110,'单列车能量回收',2000,12,'single-train','carbon/singleTrain/index',1,0,'C','0','0','carbon:singleTrain:list','chart','admin',NOW()
WHERE NOT EXISTS(SELECT 1 FROM sys_menu WHERE perms='carbon:singleTrain:list');
INSERT INTO sys_menu(menu_id,menu_name,parent_id,order_num,path,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time)
SELECT 2111,'查询任务',2110,1,'',1,0,'F','0','0','carbon:singleTrain:query','#','admin',NOW()
WHERE NOT EXISTS(SELECT 1 FROM sys_menu WHERE perms='carbon:singleTrain:query');
INSERT INTO sys_menu(menu_id,menu_name,parent_id,order_num,path,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time)
SELECT 2112,'维护数据版本',2110,2,'',1,0,'F','0','0','carbon:singleTrain:version','#','admin',NOW()
WHERE NOT EXISTS(SELECT 1 FROM sys_menu WHERE perms='carbon:singleTrain:version');
INSERT INTO sys_menu(menu_id,menu_name,parent_id,order_num,path,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time)
SELECT 2113,'提交任务',2110,3,'',1,0,'F','0','0','carbon:singleTrain:run','#','admin',NOW()
WHERE NOT EXISTS(SELECT 1 FROM sys_menu WHERE perms='carbon:singleTrain:run');
INSERT INTO sys_menu(menu_id,menu_name,parent_id,order_num,path,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time)
SELECT 2114,'取消任务',2110,4,'',1,0,'F','0','0','carbon:singleTrain:cancel','#','admin',NOW()
WHERE NOT EXISTS(SELECT 1 FROM sys_menu WHERE perms='carbon:singleTrain:cancel');
INSERT INTO sys_menu(menu_id,menu_name,parent_id,order_num,path,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time)
SELECT 2115,'下载结果',2110,5,'',1,0,'F','0','0','carbon:singleTrain:download','#','admin',NOW()
WHERE NOT EXISTS(SELECT 1 FROM sys_menu WHERE perms='carbon:singleTrain:download');
INSERT INTO sys_role_menu(role_id,menu_id)
SELECT r.role_id,m.menu_id FROM sys_role r JOIN sys_menu m ON m.perms LIKE 'carbon:singleTrain:%'
LEFT JOIN sys_role_menu rm ON rm.role_id=r.role_id AND rm.menu_id=m.menu_id
WHERE r.role_key='admin' AND rm.role_id IS NULL;
