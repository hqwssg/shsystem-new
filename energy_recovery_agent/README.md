# 能量回收调度（MySQL，挂在 RuoYi 单体下）

平台数据层连接总系统 MySQL `carbon_emissions`，表前缀 `energy_`。算法文件由交付包同步进本目录；`database/mysql.py`、`database/cli.py`、`database/worker.py` 保持 MySQL 适配，不要用 PostgreSQL 交付包覆盖。

2026-10-11 已将现有五类任务的算法同步到 `new_function/algorithm_release_20261010_v1`，本地版本为 `2026.10.10.1-mysql-five-tasks`。升级范围、数据模板、验证记录和回退方法见 [五类任务升级说明](docs/five_task_upgrade_20261010.md)。`LOCAL_ALGORITHM_UPDATE.json` 记录本次本地修改；原交付包的发布清单继续作为历史来源记录，不代表本地修改已完成正式验收。

## 建表

2026-10-12 增量接入第六类任务“储能选址与定容规划”，当前本地版本为 `2026.10.10.1-mysql-six-tasks`。中文模板、参数、结果接口、隔离验证和回退说明见 [储能规划接入说明](docs/storage_planning_integration_20261011.md)。此前五类升级记录保持保留，本次没有修改现有业务数据库。

执行 `shuohuang-main/sql/carbon-energy/V1__energy_tables.sql` 和 `V2__menus.sql`。

第六类任务须先执行 `shuohuang-main/sql/carbon-energy/V3__storage_planning.sql`，再更新算法和平台代码。已有 V1/V2 环境只需增量执行 V3；外部算法目录内提供同内容 MySQL V3 副本。

## 环境变量

```
ENERGY_DATABASE_URL=mysql://user:pass@127.0.0.1:3306/carbon_emissions
ENERGY_PYTHON=python
ENERGY_PROJECT_ROOT=<本目录>
ENERGY_UPLOAD_DIR=<上传目录>
```

`ruoyi-admin` 通过 `python -m database.cli` 发布版本、创建/取消任务，并在进程内线程池调用 `worker-once --run-id` 求解。不需要单独启动 worker 进程。

下次收算法包：

```
python tools/sync_algorithm_drop.py --source <交付包目录>
```
