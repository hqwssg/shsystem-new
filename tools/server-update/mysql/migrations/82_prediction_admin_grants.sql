-- Ensure the prediction module can be read by every authenticated account and
-- operated by platform administrators and the designated specialist roles.
-- This migration is additive and idempotent; it never removes user data or
-- changes existing role assignments.
SET NAMES utf8mb4;
START TRANSACTION;

SET @prediction_parent := (
    SELECT menu_id FROM sys_menu WHERE path = 'carbon-permissions' LIMIT 1
);
SET @prediction_parent := COALESCE(@prediction_parent,
    (SELECT menu_id FROM sys_menu WHERE perms = 'carbon:system:view' LIMIT 1), 0);

INSERT INTO sys_menu
    (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,
     menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT '碳排放趋势预测', @prediction_parent, 12, 'prediction', 'carbon/prediction', '',
       'CarbonPrediction', 1, 0, 'C', '0', '0', 'carbon:prediction:view', 'data-line',
       'admin', NOW(), '', NULL, '碳排放趋势预测模块查看权限'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:prediction:view');

INSERT INTO sys_menu
    (menu_name,parent_id,order_num,path,component,query,route_name,is_frame,is_cache,
     menu_type,visible,status,perms,icon,create_by,create_time,update_by,update_time,remark)
SELECT seed.menu_name, parent.menu_id, seed.order_num, '#', '', '', '', 1, 0, 'F', '0', '0',
       seed.perms, '#', 'admin', NOW(), '', NULL, seed.menu_name
FROM (
    SELECT '预测数据维护' AS menu_name, 'carbon:prediction:data:edit' AS perms, 1 AS order_num
    UNION ALL SELECT '预测异常复核', 'carbon:prediction:review', 2
    UNION ALL SELECT '预测模型训练', 'carbon:prediction:model', 3
    UNION ALL SELECT '生成趋势预测', 'carbon:prediction:forecast', 4
) seed
JOIN sys_menu parent ON parent.perms = 'carbon:prediction:view'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu existing WHERE existing.perms = seed.perms);

-- Platform-wide administrators receive all five prediction permissions even if
-- their role ID was changed by an import or a role-renumbering script.
INSERT IGNORE INTO sys_role_menu (role_id, menu_id)
SELECT role.role_id, menu.menu_id
FROM sys_role role
JOIN sys_menu menu ON menu.perms IN (
    'carbon:prediction:view','carbon:prediction:data:edit','carbon:prediction:review',
    'carbon:prediction:model','carbon:prediction:forecast')
WHERE role.status = '0' AND role.del_flag = '0'
  AND (
    LOWER(TRIM(role.role_key)) IN (
      'admin','company_admin','system_admin','platform_admin','super_admin',
      'sys_admin','systemadministrator','platformadministrator','companyadministrator'
    )
    OR TRIM(role.role_name) IN ('系统管理员','超级管理员','平台管理员','公司级系统管理员','公司管理员')
  );

-- Specialist roles retain the intended least-privilege split: they may view
-- data, while only assigned operators can mutate or generate predictions.
INSERT IGNORE INTO sys_role_menu (role_id, menu_id)
SELECT role.role_id, menu.menu_id
FROM sys_role role
JOIN sys_menu menu ON (
    (role.role_key = 'carbon_accountant' AND menu.perms IN
      ('carbon:prediction:view','carbon:prediction:model','carbon:prediction:forecast')) OR
    (role.role_key = 'prediction_analyst' AND menu.perms IN
      ('carbon:prediction:view','carbon:prediction:model','carbon:prediction:forecast')) OR
    (role.role_key = 'carbon_data_entry' AND menu.perms IN
      ('carbon:prediction:view','carbon:prediction:data:edit')) OR
    (role.role_key = 'carbon_reviewer' AND menu.perms IN
      ('carbon:prediction:view','carbon:prediction:review')) OR
    (role.role_key IN ('region_admin','department_admin','carbon_auditor')
      AND menu.perms = 'carbon:prediction:view')
)
WHERE role.status = '0' AND role.del_flag = '0';

INSERT IGNORE INTO sys_role_menu (role_id, menu_id)
SELECT relation.role_id, menu.parent_id
FROM sys_role_menu relation
JOIN sys_menu menu ON menu.menu_id = relation.menu_id
WHERE menu.parent_id > 0;

COMMIT;
