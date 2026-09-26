-- Energy module menus. Do not reuse report or goview permissions.

INSERT INTO sys_menu
SELECT 2090, '重空协同与能量优化', 2000, 11, 'energy', 'carbon/energy/index', '', '', 1, 0, 'C', '0', '0',
       'carbon:energy:list', 'chart', 'admin', NOW(), '', NULL, '能量回收调度任务列表'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:list');

INSERT INTO sys_menu
SELECT 2091, '任务查询', 2090, 1, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:query', '#', 'admin', NOW(), '', NULL, '查询能量任务'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:query');

INSERT INTO sys_menu
SELECT 2092, '发布数据版本', 2090, 2, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:version', '#', 'admin', NOW(), '', NULL, '发布不可变输入版本'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:version');

INSERT INTO sys_menu
SELECT 2093, '提交任务', 2090, 3, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:run', '#', 'admin', NOW(), '', NULL, '创建算法任务'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:run');

INSERT INTO sys_menu
SELECT 2094, '取消任务', 2090, 4, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:cancel', '#', 'admin', NOW(), '', NULL, '取消非终态任务'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:cancel');

INSERT INTO sys_menu
SELECT 2095, '下载工件', 2090, 5, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:download', '#', 'admin', NOW(), '', NULL, '下载结果工件'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:download');

INSERT INTO sys_menu
SELECT 2096, '项目对照', 2090, 6, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:project', '#', 'admin', NOW(), '', NULL, '维护部门与项目对照'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:project');

INSERT INTO sys_menu
SELECT 2097, '删除任务', 2090, 7, '', '', '', '', 1, 0, 'F', '0', '0',
       'carbon:energy:remove', '#', 'admin', NOW(), '', NULL, '删除任意状态任务'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:energy:remove');

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT r.role_id, m.menu_id
FROM sys_role r
JOIN sys_menu m ON m.perms IN (
  'carbon:energy:list','carbon:energy:query','carbon:energy:version','carbon:energy:run',
  'carbon:energy:cancel','carbon:energy:download','carbon:energy:project','carbon:energy:remove'
)
LEFT JOIN sys_role_menu rm ON rm.role_id = r.role_id AND rm.menu_id = m.menu_id
WHERE r.role_key = 'admin' AND rm.role_id IS NULL;
