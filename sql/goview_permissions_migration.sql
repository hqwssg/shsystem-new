-- Idempotent GoView permission/menu migration.
-- The legacy goview_permissions.sql used fixed IDs (2000-2053), which could
-- collide with menus already present on a production database.  This version
-- uses permission/path keys and AUTO_INCREMENT IDs.
SET NAMES utf8mb4;

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '碳排放平台权限',0,5,'carbon-permissions',NULL,'','',1,0,'M','1','0','', 'dashboard','admin',NOW(),'',NULL,'碳排放平台按钮与GoView权限'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE path='carbon-permissions');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目管理',r.menu_id,1,'goview-project',NULL,'','',1,0,'M','1','0','goview:project:*','#','admin',NOW(),'',NULL,'GoView项目管理'
FROM sys_menu r WHERE r.path='carbon-permissions' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:*');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目查看',m.menu_id,1,'','','','',1,0,'F','1','0','goview:project:view','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:project:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:view');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目创建',m.menu_id,2,'','','','',1,0,'F','1','0','goview:project:create','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:project:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:create');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目编辑',m.menu_id,3,'','','','',1,0,'F','1','0','goview:project:edit','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:project:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:edit');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目删除',m.menu_id,4,'','','','',1,0,'F','1','0','goview:project:delete','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:project:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:delete');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目发布',m.menu_id,5,'','','','',1,0,'F','1','0','goview:project:publish','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:project:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:publish');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '项目复制',m.menu_id,6,'','','','',1,0,'F','1','0','goview:project:copy','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:project:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:project:copy');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '模板管理',r.menu_id,2,'goview-template',NULL,'','',1,0,'M','1','0','goview:template:*','#','admin',NOW(),'',NULL,'GoView模板管理' FROM sys_menu r WHERE r.path='carbon-permissions' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:template:*');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '查看我的模板',m.menu_id,1,'','','','',1,0,'F','1','0','goview:template:view','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:template:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:template:view');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '查看模板市场',m.menu_id,2,'','','','',1,0,'F','1','0','goview:template:market','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:template:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:template:market');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '模板创建',m.menu_id,3,'','','','',1,0,'F','1','0','goview:template:create','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:template:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:template:create');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '模板使用',m.menu_id,4,'','','','',1,0,'F','1','0','goview:template:use','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:template:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:template:use');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '模板删除',m.menu_id,5,'','','','',1,0,'F','1','0','goview:template:delete','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:template:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:template:delete');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '图表编辑',r.menu_id,3,'goview-chart',NULL,'','',1,0,'M','1','0','goview:chart:*','#','admin',NOW(),'',NULL,'GoView图表编辑' FROM sys_menu r WHERE r.path='carbon-permissions' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:chart:*');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '编辑画布',m.menu_id,1,'','','','',1,0,'F','1','0','goview:chart:edit','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:chart:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:chart:edit');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '图表预览',m.menu_id,2,'','','','',1,0,'F','1','0','goview:chart:preview','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:chart:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:chart:preview');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '图表保存',m.menu_id,3,'','','','',1,0,'F','1','0','goview:chart:save','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:chart:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:chart:save');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '组件管理',m.menu_id,4,'','','','',1,0,'F','1','0','goview:chart:component:*','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:chart:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:chart:component:*');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '数据配置',m.menu_id,5,'','','','',1,0,'F','1','0','goview:chart:data:config','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:chart:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:chart:data:config');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '数据池管理',r.menu_id,4,'goview-data',NULL,'','',1,0,'M','1','0','goview:data:*','#','admin',NOW(),'',NULL,'GoView数据池管理' FROM sys_menu r WHERE r.path='carbon-permissions' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:data:*');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '数据池查看',m.menu_id,1,'','','','',1,0,'F','1','0','goview:data:view','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:data:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:data:view');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '数据池创建',m.menu_id,2,'','','','',1,0,'F','1','0','goview:data:create','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:data:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:data:create');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '数据池编辑',m.menu_id,3,'','','','',1,0,'F','1','0','goview:data:edit','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:data:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:data:edit');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '数据池删除',m.menu_id,4,'','','','',1,0,'F','1','0','goview:data:delete','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:data:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:data:delete');

INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT 'GoView系统设置',r.menu_id,5,'goview-system',NULL,'','',1,0,'M','1','0','goview:system:*','#','admin',NOW(),'',NULL,'GoView系统设置' FROM sys_menu r WHERE r.path='carbon-permissions' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:system:*');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '主题切换',m.menu_id,1,'','','','',1,0,'F','1','0','goview:system:theme','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:system:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:system:theme');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '语言切换',m.menu_id,2,'','','','',1,0,'F','1','0','goview:system:lang','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:system:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:system:lang');
INSERT INTO sys_menu (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '系统配置',m.menu_id,3,'','','','',1,0,'F','1','0','goview:system:setting','#','admin',NOW(),'',NULL,'' FROM sys_menu m WHERE m.perms='goview:system:*' AND NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='goview:system:setting');

INSERT INTO sys_role_menu (role_id,menu_id)
SELECT r.role_id,m.menu_id FROM sys_role r JOIN sys_menu m ON m.perms LIKE 'goview:%'
LEFT JOIN sys_role_menu rm ON rm.role_id=r.role_id AND rm.menu_id=m.menu_id
WHERE r.role_key IN ('admin', 'company_admin') AND rm.role_id IS NULL;
