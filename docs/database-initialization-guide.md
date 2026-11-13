# 数据库初始化说明

本文用于在新电脑或新服务器上初始化本项目的 MySQL 数据库。数据库名固定为 `carbon_emissions`。已有生产库请阅读“已有数据库升级”，不要重新执行全量基础脚本。

## 1. 数据库组成

| 文件或目录 | 作用 | 是否首次执行 |
| --- | --- | --- |
| `sql/carbon_emissions.sql` | RuoYi 主系统基础表、账号、组织、菜单和系统参数 | 是，仅限空库 |
| `tpfhs-9/backend/src/main/resources/schema.sql` | 碳排放模型基础表、字典、节点和因子 | 是 |
| `schema-update-*.sql` | 采集点、人工审核、数据关联、因子、来源节点等增量表结构 | 按顺序 |
| `sql/carbon-report/` | 报告、报告图片、主体映射和报告菜单 | 按顺序 |
| `sql/carbon-energy/` | 能耗分析、重空协同、完整示例数据和储能规划 | 按顺序 |
| `sql/carbon-analysis/` | 能耗统计分析菜单和示例展示数据 | 按顺序 |
| `sql/carbon-single-train/` | 单列车能量回收模块表和菜单 | 按顺序 |
| `docker/mysql/db/` | 由 `docker/copy.sh` 生成的 Docker 初始化副本 | Docker 首次启动时自动执行 |

`sql/carbon_emissions.sql` 含有 `DROP TABLE`，只允许用于新建空数据库。根目录的 `sql/schema_1.sql` 是历史补充脚本，不是标准初始化入口；标准模型基础脚本是 `tpfhs-9/backend/src/main/resources/schema.sql`。

## 2. 环境要求

- MySQL 5.7 或兼容的 MariaDB。
- MySQL 客户端可执行文件 `mysql`、`mysqldump` 在 PATH 中。
- 所有连接和 SQL 文件使用 `utf8mb4`，默认排序规则使用 `utf8mb4_unicode_ci`。
- 在仓库根目录执行命令。

Windows 独立 MySQL 在 `my.ini` 的 `[mysqld]` 中确认：

```ini
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
```

Linux 可在 `/etc/my.cnf` 或对应 MySQL 配置文件设置同名参数。Docker 配置已经包含这些设置。

## 3. 全新数据库初始化

### 3.1 创建数据库

PowerShell：

```powershell
$env:MYSQL_PWD = Read-Host 'MySQL root 密码'
mysql --default-character-set=utf8mb4 -uroot -e "CREATE DATABASE IF NOT EXISTS carbon_emissions DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 3.2 按顺序执行基础表和功能迁移

下面脚本会逐个执行 SQL，任意一步失败都会停止；路径通过 MySQL `source` 读取，避免 PowerShell 管道造成中文乱码。

```powershell
function Invoke-CarbonSql([string]$File) {
    $Path = (Resolve-Path -LiteralPath $File).Path.Replace('\', '/')
    Write-Host "Executing $File"
    mysql --default-character-set=utf8mb4 -uroot carbon_emissions --execute="source $Path"
    if ($LASTEXITCODE -ne 0) { throw "SQL failed: $File" }
}

$Files = @(
    'sql/carbon_emissions.sql',
    'sql/logging_migration.sql',
    'tpfhs-9/backend/src/main/resources/schema.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260916-charset-repair.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20261009-fossil-factor-units.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20261010-collection-cycle.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20261015-source-node.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20261019-node-factor-snapshot.sql',
    'sql/carbon-report/V1__report_tables.sql',
    'sql/carbon_permission_model.sql',
    'sql/goview_permissions_migration.sql',
    'sql/carbon_module_permissions.sql',
    'sql/carbon-report/V3__menus.sql',
    'sql/carbon-report/V11__shuohuang_project_integration.sql',
    'sql/carbon-report/V12__local_observation_fixtures.sql',
    'sql/carbon-report/V13__report_subject_alignment.sql',
    'sql/carbon-report/V14__calculation_factor_compatibility.sql',
    'sql/carbon-report/V15__report_file_content.sql',
    'sql/carbon-report/V16__default_report_images.sql',
    'sql/carbon-report/V17__report_subject_mapping_repair.sql',
    'sql/carbon-energy/V1__energy_tables.sql',
    'sql/carbon-energy/V2__menus.sql'
)

foreach ($File in $Files) { Invoke-CarbonSql $File }

# V5 会读取 zhongkong_data 中的 28 个原始文件并生成完整朔黄示例 SQL。
python tools/zhongkong/generate_dataset_sql.py
if ($LASTEXITCODE -ne 0) { throw '朔黄示例 SQL 生成失败' }

$FilesAfterDataset = @(
    'sql/carbon-energy/V5__shuohuang_full_dataset.sql',
    'sql/carbon-energy/V6__train_telemetry_segment_energy.sql',
    'sql/carbon-energy/V7__portable_energy_compatibility.sql',
    'sql/carbon-energy/V8__fix_energy_run_delete.sql',
    'sql/carbon-energy/V10__remove_compatibility_fixtures.sql',
    'sql/carbon-energy/V11__storage_planning.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260912.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260921-collection-status.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260921-validation-idempotency-exclusion.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260923-collection-rollover.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260924-manual-review.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20260930-data-linkage.sql',
    'sql/carbon_collection_scope_permissions.sql',
    'sql/carbon_auto_collection_manual_permission.sql',
    'sql/system_config_unique.sql',
    'sql/carbon_statistics_demo.sql',
    'sql/carbon-analysis/V1__menus.sql',
    'sql/carbon-analysis/V2__display_seed.sql',
    'tpfhs-9/backend/src/main/resources/schema-update-20261013-meter-model-seed.sql',
    'sql/carbon-single-train/V0__preflight.sql',
    'sql/carbon-single-train/V1__tables.sql',
    'sql/carbon-single-train/V2__menus.sql'
)

foreach ($File in $FilesAfterDataset) { Invoke-CarbonSql $File }
Remove-Item Env:MYSQL_PWD
```

示例脚本会创建系统参数、采集点、人工审核、报告、统计查询、重空协同和单列车模块的数据。若不需要演示数据，可在初始化前移除对应的 `V5`、`V12`、`V41`、统计示例等脚本，但服务器和本地环境的数据将不再一致。

### 3.3 初始化后检查

```powershell
mysql --default-character-set=utf8mb4 -uroot carbon_emissions --execute="SELECT @@character_set_database,@@collation_database; SHOW TABLES;"
mysql --default-character-set=utf8mb4 -uroot carbon_emissions --execute="SHOW TABLES LIKE 'emission_collection_record'; SHOW TABLES LIKE 'emission_collection_record_audit'; SHOW TABLES LIKE 'energy_run'; SHOW TABLES LIKE 'single_run';"
mysql --default-character-set=utf8mb4 -uroot carbon_emissions --execute="SELECT config_key,config_value FROM sys_config WHERE config_key='carbon.collection.manual.auto-approve';"
```

`carbon.collection.manual.auto-approve` 默认值为 `false`。只有拥有审核权限的用户且该参数开启时，人工采集数据才会自动审核通过。

朔黄示例数据应满足：28 个原始文件、33 个主线车站、1390 个线路区间、76 个供电臂、2 种列车参数、2 个储能设备和运行图示例。

## 4. Docker 首次初始化

Docker 只会在 MySQL 数据目录为空时自动执行 `/docker-entrypoint-initdb.d/` 下的 SQL。先构建部署目录：

```powershell
cd docker
sh copy.sh
```

`copy.sh` 会根据当前源码生成并按 `zz00`、`zz01`……顺序复制初始化 SQL。确认 `docker/mysql/data/` 为空且没有需要保留的数据后启动：

```powershell
$env:MYSQL_ROOT_PASSWORD = '替换为数据库密码'
$env:GOVIEW_AUDIT_SECRET = '替换为随机长字符串'
docker compose up -d ruoyi-db
docker compose logs -f ruoyi-db
```

看到 `ready for connections` 后启动业务容器：

```powershell
docker compose up -d ruoyi-web ruoyi-screen
docker compose ps
```

已有 Docker 数据目录时，不要删除 `docker/mysql/data/`，也不要执行 `docker compose down -v`。应使用服务器更新包中的增量迁移脚本。

## 5. 已有数据库升级

升级前备份：

```bash
mysqldump --default-character-set=utf8mb4 -uroot -p \
  --single-transaction --routines --triggers carbon_emissions \
  > carbon_emissions-backup.sql
```

已有库禁止执行 `sql/carbon_emissions.sql`。只执行尚未应用的增量迁移，优先使用服务器更新包的 `deploy-update.sh`，它会自动备份并按顺序执行迁移。手工升级时至少核对：

```text
schema-update-20260916-charset-repair.sql
schema-update-20260921-collection-status.sql
schema-update-20260921-validation-idempotency-exclusion.sql
schema-update-20260923-collection-rollover.sql
schema-update-20260924-manual-review.sql
schema-update-20260930-data-linkage.sql
schema-update-20261009-fossil-factor-units.sql
schema-update-20261010-collection-cycle.sql
schema-update-20261013-meter-model-seed.sql
schema-update-20261015-source-node.sql
schema-update-20261019-node-factor-snapshot.sql
```

不要通过“重启数据库”解决缺表问题。重启不会删除表；若表缺失，应确认执行的是正确数据库、正确数据卷和对应增量迁移。

## 6. 中文乱码和数据安全

- MySQL 客户端始终带 `--default-character-set=utf8mb4`。
- 不要使用 `Get-Content file.sql | mysql`。
- 不要用 ANSI/GBK 编辑器另存 SQL。
- JDBC 使用 `characterEncoding=UTF-8`，不要把 `utf8mb4` 填入 `characterEncoding`。
- 不要在生产库重复执行基础脚本。
- 备份并长期保留 MySQL 数据、GoView SQLite、上传文件和报表文件。
- 数据库重启前后可使用 `tools/verify-data-persistence.ps1` 对比各表记录数。

完整服务器升级、回滚和验收流程见 [server-update-instructions.md](server-update-instructions.md)。
