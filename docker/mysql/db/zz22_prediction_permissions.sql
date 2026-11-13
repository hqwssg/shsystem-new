-- Carbon trend prediction menu and operation permissions. Safe to rerun.
SET NAMES utf8mb4;

INSERT INTO sys_menu
    (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,
     menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '碳排放趋势预测',2000,12,'prediction','carbon/prediction','','CarbonPrediction',1,0,
       'C','0','0','carbon:prediction:view','data-line','admin',NOW(),'',NULL,'访问碳排放趋势预测模块'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms='carbon:prediction:view');

INSERT INTO sys_menu
    (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,
     menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT permission_name,parent.menu_id,permissions.order_num,'#','','','',1,0,'F','0','0',permission_key,'#','admin',NOW(),'',NULL,permission_name
FROM (
    SELECT '预测数据维护' permission_name,'carbon:prediction:data:edit' permission_key,1 order_num
    UNION ALL SELECT '预测异常复核','carbon:prediction:review',2
    UNION ALL SELECT '预测模型训练','carbon:prediction:model',3
    UNION ALL SELECT '生成趋势预测','carbon:prediction:forecast',4
) permissions
JOIN sys_menu parent ON parent.perms='carbon:prediction:view'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu existing WHERE existing.perms=permissions.permission_key);

INSERT INTO sys_role_menu (role_id,menu_id)
SELECT role.role_id,menu.menu_id
FROM sys_role role
JOIN sys_menu menu ON menu.perms IN (
    'carbon:prediction:view','carbon:prediction:data:edit','carbon:prediction:review',
    'carbon:prediction:model','carbon:prediction:forecast')
LEFT JOIN sys_role_menu assigned ON assigned.role_id=role.role_id AND assigned.menu_id=menu.menu_id
WHERE role.role_key IN ('admin','company_admin') AND assigned.role_id IS NULL;

INSERT INTO sys_role_menu (role_id,menu_id)
SELECT role.role_id,menu.menu_id
FROM sys_role role
JOIN sys_menu menu ON (
    (role.role_key='carbon_data_entry' AND menu.perms IN ('carbon:prediction:view','carbon:prediction:data:edit')) OR
    (role.role_key='carbon_reviewer' AND menu.perms IN ('carbon:prediction:view','carbon:prediction:review')) OR
    (role.role_key='carbon_accountant' AND menu.perms IN ('carbon:prediction:view','carbon:prediction:model','carbon:prediction:forecast')) OR
    (role.role_key='carbon_auditor' AND menu.perms='carbon:prediction:view'))
LEFT JOIN sys_role_menu assigned ON assigned.role_id=role.role_id AND assigned.menu_id=menu.menu_id
WHERE assigned.role_id IS NULL;
