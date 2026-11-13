# PostgreSQL备份恢复预案与本地演练

## 1. 目标

备份只有经过恢复验证才可作为上线证据。`tools/production_database_backup_restore.py`使用`pg_dump`生成custom格式逻辑备份，在全新隔离数据库中执行`pg_restore`，再检查迁移版本、关键表和关键表行数。

本地通过仅证明当前软件结构可以逻辑备份和恢复，不证明甲方备份介质、保留周期、异地复制、RPO或RTO满足生产要求。

## 2. 安全约束

- 恢复库名称必须以`_restore_test`结尾，且不得等于源库。
- 如果恢复库已经存在，工具拒绝覆盖，不会自动删除未知数据库。
- 默认演练完成后只删除本次新建的隔离恢复库；备份文件和报告保留。
- 演练要求源库没有`pending/validating/running`任务，并通过导出的只读一致性快照同时完成源表计数与`pg_dump`。
- 密码通过PG环境变量传给子进程，不进入`pg_dump/pg_restore`命令行或报告。
- 不使用`--clean`恢复到业务库，不提供破坏性down migration。

## 3. 本地命令

```powershell
$env:SIMULATION_BACKUP_SOURCE_DATABASE_URL='postgresql://.../carbon_emissions'
$env:POSTGRES_ADMIN_URL='postgresql://.../postgres'

python tools/production_database_backup_restore.py `
  --restore-database carbon_emissions_restore_test `
  --pg-bin '<PostgreSQL bin目录>' `
  --output-dir outputs/production_backup_restore_drill
```

正常结果要求`accepted=true`、五项检查全部通过且`restore_cleaned_up=true`。输出包括备份文件、`backup_restore_drill.json`和`BACKUP_RESTORE_DRILL.md`。

## 4. 正式环境演练

1. 记录源库版本、软件包哈希、备份开始时间和操作者。
2. 在批准的备份介质创建备份，计算SHA-256并验证目录可读。
3. 在与生产隔离的目标实例创建全新恢复库。
4. 执行恢复和结构/行数检查，运行数据库健康检查与代表性只读查询。
5. 记录备份窗口、恢复耗时、可恢复时间点、数据差异和容量。
6. 清理隔离库前由数据库管理员确认，无误后按变更流程删除。
7. 由甲方批准RPO、RTO、保留周期、加密、异地副本和演练频率。

## 5. 恢复决策

发生迁移失败或数据损坏时，先停止平台写入和worker，再选择恢复点。恢复完成后必须使用与恢复点schema兼容的软件版本，执行迁移校验和、账号权限、五类任务和结果审计。不得只恢复数据库而继续运行不兼容的新代码。
