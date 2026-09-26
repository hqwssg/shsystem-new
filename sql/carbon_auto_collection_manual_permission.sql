-- 采集点抄表方式修改权限。
-- 在常规若依/碳排放菜单权限之后执行，可重复执行。
UPDATE sys_menu
SET menu_name = '采集点抄表方式修改',
    remark = '允许被授权人员修改采集点的自动/人工抄表方式'
WHERE perms = 'carbon:data:auto:manual';

INSERT INTO sys_menu
    (menu_name, parent_id, order_num, path, component, query, route_name,
     is_frame, is_cache, menu_type, visible, status, perms, icon, create_by, create_time, remark)
SELECT '采集点抄表方式修改', 2000, 35, '', '', '', '',
       1, 0, 'F', '1', '0', 'carbon:data:auto:manual', '#', 'admin', NOW(),
       '允许被授权人员修改采集点的自动/人工抄表方式'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'carbon:data:auto:manual');

-- 不给任何业务角色预置该权限。管理员可在角色管理中按需授予；
-- 未明确授权时，采集点的抄表方式为只读。
