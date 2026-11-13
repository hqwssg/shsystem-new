-- Complete role and permission matrix for every carbon and GoView module.
-- Idempotent on MySQL 5.7+/MariaDB. No sample users or account credentials are created.
SET NAMES utf8mb4;
START TRANSACTION;

CREATE TEMPORARY TABLE tmp_complete_role_seed (
  role_name VARCHAR(64) NOT NULL,
  role_key VARCHAR(100) NOT NULL PRIMARY KEY,
  role_sort INT NOT NULL,
  data_scope CHAR(1) NOT NULL,
  remark VARCHAR(500) NOT NULL
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO tmp_complete_role_seed VALUES
  ('公司级管理员','company_admin',10,'1','公司全域配置与授权；范例：总部碳管理平台主管'),
  ('地区管理员','region_admin',20,'4','本地区及下属部门管理；范例：原平分公司系统管理员'),
  ('部门管理员','department_admin',30,'4','本部门及下属部门业务管理；范例：供电部部门管理员'),
  ('碳核算员','carbon_accountant',40,'4','核算、统计、报告与不确定性分析；范例：安全环保部碳核算专员'),
  ('数据录入员','carbon_data_entry',50,'3','本部门活动数据录入与提交；范例：月度能耗填报人员'),
  ('数据审核员','carbon_reviewer',60,'4','区域内数据和预测异常审核；范例：分公司数据复核人员'),
  ('审计查看员','carbon_auditor',70,'1','公司范围只读审计；范例：内控审计人员'),
  ('大屏运维员','screen_operator',80,'1','大屏、模板和数据源维护；范例：信息化大屏运维人员'),
  ('供电采集员','electricity_collector',90,'4','按授权范围维护电表和采集点；范例：站区供电抄表人员'),
  ('重空协同操作员','energy_operator',100,'4','维护能量数据版本并执行重空协同任务；范例：运输调度优化人员'),
  ('单列车操作员','single_train_operator',110,'4','维护单列车数据版本并执行回收任务；范例：机辆能耗分析人员'),
  ('趋势预测分析员','prediction_analyst',120,'4','训练预测模型并生成趋势预测；范例：碳排放预测分析人员');

INSERT INTO sys_role
  (role_name,role_key,role_sort,data_scope,menu_check_strictly,dept_check_strictly,
   status,del_flag,create_by,create_time,remark)
SELECT seed.role_name,seed.role_key,seed.role_sort,seed.data_scope,1,1,
       '0','0','admin',NOW(),seed.remark
FROM tmp_complete_role_seed seed
WHERE NOT EXISTS (
  SELECT 1 FROM sys_role existing
  WHERE existing.role_key COLLATE utf8mb4_unicode_ci = seed.role_key COLLATE utf8mb4_unicode_ci
);

UPDATE sys_role role
JOIN tmp_complete_role_seed seed
  ON role.role_key COLLATE utf8mb4_unicode_ci = seed.role_key COLLATE utf8mb4_unicode_ci
SET role.role_name=seed.role_name,
    role.role_sort=seed.role_sort,
    role.data_scope=seed.data_scope,
    role.remark=seed.remark,
    role.update_by='admin',
    role.update_time=NOW();

UPDATE sys_role
SET remark='系统全功能与全数据管理员；范例：平台最高管理员',
    update_by='admin',update_time=NOW()
WHERE role_key='admin';

UPDATE sys_role
SET remark='基础登录角色，不授予碳业务模块；范例：仅使用个人中心的普通用户',
    update_by='admin',update_time=NOW()
WHERE role_key='common';

-- Rebuild only carbon/GoView grants for managed roles. Native RuoYi system
-- permissions and user-role assignments remain untouched.
DELETE relation
FROM sys_role_menu relation
JOIN sys_role role ON role.role_id=relation.role_id
JOIN sys_menu menu ON menu.menu_id=relation.menu_id
WHERE role.role_key IN (
  'admin','company_admin','region_admin','department_admin','carbon_accountant',
  'carbon_data_entry','carbon_reviewer','carbon_auditor','screen_operator',
  'electricity_collector','energy_operator','single_train_operator','prediction_analyst'
)
AND (menu.perms LIKE 'carbon:%' OR menu.perms LIKE 'goview:%');

INSERT IGNORE INTO sys_role_menu(role_id,menu_id)
SELECT role.role_id,menu.menu_id
FROM sys_role role
JOIN sys_menu menu ON menu.status='0' AND menu.perms IS NOT NULL AND menu.perms<>''
WHERE role.status='0' AND role.del_flag='0'
AND (
  -- Platform administrators retain every carbon and GoView capability.
  (role.role_key IN ('admin','company_admin')
    AND (menu.perms LIKE 'carbon:%' OR menu.perms LIKE 'goview:%'))

  -- Regional administrators manage the regional workflow, but destructive
  -- energy project deletion and GoView design stay company-level.
  OR (role.role_key='region_admin' AND menu.perms IN (
    'carbon:model:view','carbon:model:edit','carbon:model:validate',
    'carbon:params:view','carbon:params:edit','carbon:params:collection:edit',
    'carbon:screen:view',
    'carbon:data:view','carbon:data:edit','carbon:data:submit','carbon:data:review','carbon:data:lock','carbon:data:auto:manual',
    'carbon:statistics:view','carbon:statistics:export','carbon:analysis:view',
    'carbon:report:list','carbon:report:query','carbon:report:add','carbon:report:edit','carbon:report:remove',
    'carbon:report:import','carbon:report:validate','carbon:report:generate','carbon:report:download',
    'carbon:report:profile:query','carbon:report:profile:edit','carbon:uncertainty:view',
    'carbon:prediction:view','carbon:prediction:forecast',
    'carbon:energy:list','carbon:energy:query','carbon:energy:run','carbon:energy:cancel','carbon:energy:download',
    'carbon:singleTrain:list','carbon:singleTrain:query','carbon:singleTrain:run','carbon:singleTrain:cancel','carbon:singleTrain:download',
    'carbon:scope:view','carbon:scope:edit','carbon:system:view','carbon:logs:view','carbon:logs:export'
  ))

  OR (role.role_key='department_admin' AND menu.perms IN (
    'carbon:model:view','carbon:params:view','carbon:screen:view',
    'carbon:data:view','carbon:data:edit','carbon:data:submit','carbon:data:review',
    'carbon:statistics:view','carbon:analysis:view',
    'carbon:report:list','carbon:report:query','carbon:report:add','carbon:report:edit',
    'carbon:report:import','carbon:report:validate','carbon:report:profile:query','carbon:uncertainty:view',
    'carbon:prediction:view','carbon:energy:list','carbon:energy:query','carbon:energy:download',
    'carbon:singleTrain:list','carbon:singleTrain:query','carbon:singleTrain:download',
    'carbon:scope:view','carbon:scope:edit','carbon:system:view','carbon:logs:view'
  ))

  OR (role.role_key='carbon_accountant' AND menu.perms IN (
    'carbon:model:view','carbon:model:edit','carbon:model:validate',
    'carbon:params:view','carbon:params:edit','carbon:params:collection:edit','carbon:screen:view','carbon:data:view',
    'carbon:statistics:view','carbon:statistics:export','carbon:analysis:view',
    'carbon:report:list','carbon:report:query','carbon:report:add','carbon:report:edit',
    'carbon:report:import','carbon:report:validate','carbon:report:generate','carbon:report:download',
    'carbon:report:profile:query','carbon:uncertainty:view',
    'carbon:prediction:view','carbon:prediction:model','carbon:prediction:forecast',
    'carbon:energy:list','carbon:energy:query','carbon:energy:download',
    'carbon:singleTrain:list','carbon:singleTrain:query','carbon:singleTrain:download','carbon:logs:view'
  ))

  OR (role.role_key='carbon_data_entry' AND menu.perms IN (
    'carbon:params:view','carbon:data:view','carbon:data:edit','carbon:data:submit',
    'carbon:statistics:view','carbon:report:list','carbon:report:query',
    'carbon:prediction:view','carbon:prediction:data:edit'
  ))

  OR (role.role_key='carbon_reviewer' AND menu.perms IN (
    'carbon:params:view','carbon:screen:view','carbon:data:view','carbon:data:review','carbon:data:lock',
    'carbon:statistics:view','carbon:report:list','carbon:report:query','carbon:report:validate',
    'carbon:report:profile:query','carbon:prediction:view','carbon:prediction:review','carbon:logs:view'
  ))

  OR (role.role_key='carbon_auditor' AND menu.perms IN (
    'carbon:screen:view','carbon:data:view','carbon:statistics:view','carbon:statistics:export','carbon:analysis:view',
    'carbon:report:list','carbon:report:query','carbon:report:download','carbon:report:profile:query',
    'carbon:uncertainty:view','carbon:prediction:view',
    'carbon:energy:list','carbon:energy:query','carbon:energy:download',
    'carbon:singleTrain:list','carbon:singleTrain:query','carbon:singleTrain:download',
    'carbon:logs:view','carbon:logs:export'
  ))

  OR (role.role_key='screen_operator' AND (
    menu.perms IN ('carbon:screen:view','carbon:screen:edit','carbon:params:view')
    OR menu.perms LIKE 'goview:%'
  ))

  OR (role.role_key='electricity_collector' AND menu.perms IN (
    'carbon:params:view','carbon:params:collection:edit','carbon:scope:view','carbon:scope:edit'
  ))

  OR (role.role_key='energy_operator' AND menu.perms IN (
    'carbon:energy:list','carbon:energy:query','carbon:energy:version',
    'carbon:energy:run','carbon:energy:cancel','carbon:energy:download'
  ))

  OR (role.role_key='single_train_operator' AND menu.perms IN (
    'carbon:singleTrain:list','carbon:singleTrain:query','carbon:singleTrain:version',
    'carbon:singleTrain:run','carbon:singleTrain:cancel','carbon:singleTrain:download'
  ))

  OR (role.role_key='prediction_analyst' AND menu.perms IN (
    'carbon:prediction:view','carbon:prediction:model','carbon:prediction:forecast',
    'carbon:statistics:view','carbon:analysis:view','carbon:report:list','carbon:report:query'
  ))
);

-- Add all menu ancestors required to reach the assigned module entries.
INSERT IGNORE INTO sys_role_menu(role_id,menu_id)
SELECT assigned.role_id,menu.parent_id
FROM sys_role_menu assigned JOIN sys_menu menu ON menu.menu_id=assigned.menu_id
WHERE menu.parent_id>0;
INSERT IGNORE INTO sys_role_menu(role_id,menu_id)
SELECT assigned.role_id,menu.parent_id
FROM sys_role_menu assigned JOIN sys_menu menu ON menu.menu_id=assigned.menu_id
WHERE menu.parent_id>0;
INSERT IGNORE INTO sys_role_menu(role_id,menu_id)
SELECT assigned.role_id,menu.parent_id
FROM sys_role_menu assigned JOIN sys_menu menu ON menu.menu_id=assigned.menu_id
WHERE menu.parent_id>0;

DROP TEMPORARY TABLE tmp_complete_role_seed;
COMMIT;
