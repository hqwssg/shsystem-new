# 本地开发与部署指南

本文只说明在开发机或测试机上从源码初始化、构建、启动和验收系统的方法。服务器相关内容统一放在 [server-update-instructions.md](server-update-instructions.md)。

> 当前文档最后更新：2026-11-03。服务器更新包由 `tools/server-update/build-update.ps1` 生成，服务器操作步骤只维护在 [server-update-instructions.md](server-update-instructions.md)。

月度采集点核算数据功能新增于 2026-10-28。全量更新包会自动执行
`tpfhs-9/backend/src/main/resources/schema-update-20261028-collection-point-monthly-data.sql`；该迁移只创建月度表和索引，不回填或删除历史业务数据。

趋势预测自动消费开关新增于2026-11-03。已有数据库执行
`tpfhs-9/backend/src/main/resources/schema-update-20261103-trend-prediction-auto-ingest.sql`；迁移只在参数键不存在时插入默认关闭的系统内置参数，不覆盖管理员已经设置的值。执行后若若依主后端未重启，应在“系统管理 → 系统配置 → 参数设置”中点击“刷新缓存”。

### 2026-10-28 月度能耗统计分析

能耗统计分析现在统一读取 `emission_collection_node_data_month`，支持按公司/模板/核算点、能源品类或场景、部门/站点进行月、季度、年度统计，并提供原始值、修正值、核算采用值、同比/环比、修正明细和 Excel 导出。该功能复用现有月度表、模板和数据权限，不新增业务表或迁移；服务器只需随更新包替换模型 JAR 和主前端 dist。月度表不存在时接口会返回 503，不能通过回退旧核算任务总量来掩盖缺表问题。

本次不自动初始化演示数据。`scripts/energy-analysis/monthly_demo.py` 仅允许连接本机 MySQL，用于开发机或独立测试库的可回滚演示；正式服务器应直接查询真实月度结果。需要本地演示时，先备份数据库并按同一个清单执行：

```powershell
python scripts/energy-analysis/monthly_demo.py init --database carbon_emissions --user root --manifest monthly-analysis-demo-manifest.json
python scripts/energy-analysis/monthly_demo.py verify --database carbon_emissions --user root --manifest monthly-analysis-demo-manifest.json
# 验收后按清单逆序清理，不要按公司名称批量删除
python scripts/energy-analysis/monthly_demo.py clean --database carbon_emissions --user root --manifest monthly-analysis-demo-manifest.json
```

演示数据带有“本地演示-月度统计20261028”标记，不覆盖现有模板、月度记录或统计基准；不要在生产服务器执行该脚本。

## 一、系统组成与本地端口

| 模块 | 作用 | 本地端口 |
| --- | --- | ---: |
| RuoYi 主后端 | 登录、组织、人员、角色、权限及主业务 API | 8081 |
| RuoYi 主前端 | 管理后台 | 80 |
| 碳排放模型后端 | 采集点、人工采集、审核、核算和模型 API | 8082 |
| 碳排放模型前端 | 采集和核算页面 | 5177 |
| GoView 后端 | 大屏项目、用户和资源 API | 8083 |
| GoView 前端 | 大屏编辑和预览 | 3000 |
| MySQL | carbon_emissions 业务数据库 | 3306 |
| Redis | 登录令牌、缓存和任务运行数据 | 6379 |

启动后常用地址：

~~~text
管理后台：http://localhost/
碳排放模型：http://localhost:5177/
GoView：http://localhost:3000/
GoView API 文档：http://localhost:8083/doc.html

GoView 大屏通过 `/carbon-screen/` 读取主后台聚合数据；开发服务器默认代理到 `http://localhost:8081`。主后台使用其他地址时，在启动 GoView 前设置 `VITE_CARBON_SCREEN_PATH`，不要把个人电脑地址写入源码。
~~~

## 二、开发环境

| 软件 | 要求 |
| --- | --- |
| JDK | RuoYi 和碳排放模型使用 JDK 17；GoView 后端按其 pom.xml 要求运行 |
| Maven | Maven 3.8+；可使用 Maven Daemon（mvnd）加快构建 |
| Node.js | 18 或 20，npm 随 Node.js 安装 |
| pnpm | GoView 前端使用 pnpm，建议 9+ |
| Python | 3.10+，用于报表和能耗优化脚本 |
| MySQL | 5.7 或 8.0，字符集使用 utf8mb4 |
| Redis | 6+ |
| LibreOffice | 只有报表导出 Word/PDF 时需要 |

LibreOffice 不仅要有可执行命令，其动态库也必须完整。Debian/Ubuntu 镜像需包含 `libxinerama1`，openEuler 对应 `libXinerama`；项目的 Dockerfile 已包含 Debian 依赖，服务器更新脚本会在替换应用前检查实际程序和动态库。

检查工具：

~~~powershell
java -version
mvn -version
node -v
npm -v
pnpm -v
python --version
mysql --version
redis-server --version
~~~

## 三、获取源码和安装依赖

~~~powershell
git clone https://github.com/hqwssg/shuohuang.git
cd shuohuang

cd ruoyi-ui
npm ci
cd ..

cd tpfhs-9/frontend
npm ci
cd ../..

cd goview/go-view-master-fetch
corepack enable
pnpm install --frozen-lockfile
cd ../..
~~~

报表、重空协同和单列车能量回收的 Python 依赖按各目录中的 requirements*.txt 安装到虚拟环境，不要提交虚拟环境目录。运行时必须保留完整的 `energy_recovery_agent/`、`single_train_recovery_agent/` 和 `new_function/single_train_energy_optimization-f6d1797/`。

## 四、数据库初始化与升级

### 4.0 字符集、中文和排序规则约束

本项目统一使用 `utf8mb4`。此前服务器出现的混合排序规则错误，和其他电脑出现中文问号、乱码，属于同一类数据库兼容问题的不同表现：前者是列/连接排序规则不一致，后者通常是 SQL 文件或 JDBC 连接使用了三字节 `utf8`。当前版本已做以下处理：

- Docker MySQL、初始数据库和权限迁移统一使用 `utf8mb4` 与 `utf8mb4_unicode_ci`。
- JDBC 使用 Java 支持的 `characterEncoding=UTF-8`，并显式指定 MySQL 连接排序规则 `connectionCollation=utf8mb4_unicode_ci`；数据库和 SQL 客户端仍统一使用 `utf8mb4`。不要把 `utf8mb4` 直接填入 JDBC 的 `characterEncoding`，Connector/J 会报 `Unsupported character encoding 'utf8mb4'`。
- 47/48 能耗迁移对历史混合排序规则使用二进制比较，并避免创建不兼容的字符串外键。
- 首次部署和升级都会执行幂等的 `schema-update-20260916-charset-repair.sql`，只修复可识别的仓库示例乱码，不修改操作日志和用户自建历史文本。

执行 SQL 必须让 MySQL 客户端以 UTF-8 连接。不要使用 `Get-Content 文件.sql | mysql`，也不要用 ANSI/GBK 编辑器另存 SQL；命令行统一带 `--default-character-set=utf8mb4`。初始化后检查：

~~~powershell
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="SELECT @@character_set_client,@@character_set_connection,@@character_set_database,@@collation_connection,@@collation_database; SELECT table_collation,COUNT(*) FROM information_schema.tables WHERE table_schema='carbon_emissions' GROUP BY table_collation;"
~~~

新建数据库应显示 `utf8mb4`，默认排序规则为 `utf8mb4_unicode_ci`。旧数据库可能同时存在历史 `utf8mb4_general_ci` 表；只要增量迁移完整执行，不要手工批量改表或删除数据，兼容迁移会避免跨排序规则比较失败。

如果使用电脑上独立安装的 MySQL，而不是 Docker，请在 `my.ini`/`my.cnf` 的 `[mysqld]` 下设置 `character-set-server=utf8mb4` 和 `collation-server=utf8mb4_unicode_ci`，重启 MySQL 后再初始化数据库。Docker 已在 `docker/mysql/conf/client.cnf` 和 compose 参数中包含相同设置。

### 4.1 新建数据库

`sql/carbon_emissions.sql` 会删除并重建基础表，只能用于全新的空数据库。PowerShell 不要使用 `Get-Content | mysql`，该方式可能把中文转换成问号；使用 MySQL 客户端的 `source` 命令：

~~~powershell
mysql --default-character-set=utf8mb4 -uroot -p -e "CREATE DATABASE IF NOT EXISTS carbon_emissions DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_emissions.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/logging_migration.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261015-energy-attribution.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261018-calculation-company.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261019-node-factor-snapshot.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261028-collection-point-monthly-data.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260916-charset-repair.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V1__report_tables.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_permission_model.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/goview_permissions_migration.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_module_permissions.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V3__menus.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V11__shuohuang_project_integration.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V12__local_observation_fixtures.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V13__report_subject_alignment.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V14__calculation_factor_compatibility.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V15__report_file_content.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260912.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260921-collection-status.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260921-validation-idempotency-exclusion.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260923-collection-rollover.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260924-manual-review.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260930-data-linkage.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_collection_scope_permissions.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_auto_collection_manual_permission.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/system_config_unique.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V1__energy_tables.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V2__menus.sql"
python tools/zhongkong/generate_dataset_sql.py
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V5__shuohuang_full_dataset.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V6__train_telemetry_segment_energy.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V7__portable_energy_compatibility.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V8__fix_energy_run_delete.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V10__remove_compatibility_fixtures.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_statistics_demo.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-analysis/V1__menus.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-analysis/V2__display_seed.sql"
~~~

需要示例数据时再导入：

~~~powershell
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_node_chinese_fixtures.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_node_observation_fixtures.sql"
~~~

### 4.2 已有数据库升级

升级前先备份：

~~~powershell
mysqldump --default-character-set=utf8mb4 -uroot -p --single-transaction --routines --triggers carbon_emissions > carbon_emissions-backup.sql
~~~

已有数据禁止再次导入全量脚本，只执行尚未应用的增量脚本，例如：

本次版本新增的服务器增量迁移由更新包自动按顺序执行：`15c1_energy_attribution.sql`（能耗归属目录、52 条默认站点及三类采集点归属字段）、`15d_calculation_company.sql`（核算模板/任务公司归属快照）和 `15e_node_factor_snapshot.sql`（清理因子值/单位只存在一项的历史半组覆盖），并继续包含 `48e_storage_planning.sql` 与 `44_report_file_content.sql`。这些脚本均按已有数据库升级设计；不要重新导入带 `DROP TABLE` 的全量初始化脚本。

2026-10-19 报告兼容修复不新增数据库表或结构迁移，但部署时必须一起替换主系统 JAR、模型 JAR、主前端和报告 Python 渲染模块。历史任务归属、异常单位和缺失来源继续按服务端规则拦截，不能通过全量初始化 SQL、自动补零或重写旧核算结果处理。三家公司默认材料只允许使用更新包内的受控导入器先预览、备份后应用，具体步骤见 `server-update-instructions.md` 第 5.7 节。

~~~powershell
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260916-charset-repair.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261015-energy-attribution.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261018-calculation-company.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20261019-node-factor-snapshot.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260921-collection-status.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260921-validation-idempotency-exclusion.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260923-collection-rollover.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260924-manual-review.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source tpfhs-9/backend/src/main/resources/schema-update-20260930-data-linkage.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/system_config_unique.sql"
python tools/zhongkong/generate_dataset_sql.py
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V5__shuohuang_full_dataset.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V6__train_telemetry_segment_energy.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V7__portable_energy_compatibility.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V8__fix_energy_run_delete.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-energy/V10__remove_compatibility_fixtures.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon_statistics_demo.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V13__report_subject_alignment.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-report/V15__report_file_content.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-analysis/V1__menus.sql"
mysql --default-character-set=utf8mb4 -uroot -p carbon_emissions --execute="source sql/carbon-analysis/V2__display_seed.sql"
~~~

升级后检查：

~~~sql
SHOW TABLES LIKE 'emission_collection_record';
SHOW TABLES LIKE 'emission_collection_record_audit';
SHOW TABLES LIKE 'energy_run';
SHOW TABLES LIKE 'emission_energy_attribution_station';
SELECT COUNT(*) AS attribution_stations FROM emission_energy_attribution_station;
SHOW COLUMNS FROM emission_calculation_template LIKE 'company_dept_id';
SELECT config_key, config_value FROM sys_config
 WHERE config_key = 'carbon.collection.manual.auto-approve';
SELECT COUNT(*) FROM energy_dataset_file f
 JOIN energy_project_version v ON v.version_id = f.version_id
 JOIN energy_project p ON p.project_id = v.project_id
 WHERE p.project_code = 'shuohuang_demo' AND v.version_code = 'v1';
~~~

carbon.collection.manual.auto-approve 默认是 false。参数开启且提交人拥有审核权限时，人工采集数据自动审核通过；其他人员仍进入待审核状态。

重空完整示例版本应包含 28 个原始文件、33 个主线车站、1390 个线路区间、76 个供电臂、2 种列车参数、2 个储能设备和 2 列运行图列车。完整迁移只允许升级旧占位版本或重复导入相同数据摘要；遇到同名但内容不同的 `v1` 会中止，避免覆盖正式数据。

### 4.3 数据持久化和重启检查

正常重启 MySQL、三个后端或 Docker 容器不会重新初始化数据库，也不应减少任何表或记录。数据库目录被删除、换成空目录或手工重新执行 `carbon_emissions.sql` 属于“重建”，不是“重启”。

必须长期保留并备份：

| 数据 | 本地/源码位置 | Docker 持久化位置 |
| --- | --- | --- |
| MySQL 全部业务数据 | `SELECT @@datadir` 返回的目录 | `docker/mysql/data/` |
| GoView 项目、用户和页面 | `goview/go-view-serve-master/sqllite/goview.db` | `docker/web-screen/sqllite/` |
| GoView 上传资源 | `goview/upload/` | `docker/web-screen/upload/` |
| 报表和业务上传文件 | `uploadPath/` | `docker/web-main/uploadPath/` |
| Redis 登录和缓存数据 | Redis 工作目录 | `docker/web-main/redis-data/` |

不要删除上述目录，不要用空的 `goview.db` 覆盖现有文件。Redis 数据丢失会使登录令牌失效，但不应删除 MySQL 业务数据。

数据库重启前生成快照并检查，重启后比较所有表的记录数：

~~~powershell
$env:MYSQL_PWD = Read-Host 'MySQL 密码'
powershell -ExecutionPolicy Bypass -File tools/verify-data-persistence.ps1 `
  -SnapshotPath .runtime/before-db-restart.json

# 需要管理员 PowerShell；服务名按实际环境调整。
Restart-Service MySQL80

powershell -ExecutionPolicy Bypass -File tools/verify-data-persistence.ps1 `
  -CompareSnapshot .runtime/before-db-restart.json
Remove-Item Env:MYSQL_PWD
~~~

检查覆盖账号、角色、菜单、系统参数唯一性、人工审核、报表表结构、统计示例、重空数据、在线版本编辑表、五类任务和 GoView SQLite。统计示例会在模型后端启动时幂等补齐；主后端会在启动时幂等确认 `energy_version_edit_sheet` 存在，旧数据库不再因漏执行 V7 迁移导致在线编辑页面失效。如生产环境明确不需要演示数据，可设置 `CARBON_STATISTICS_DEMO_ENABLED=false`。其他正式业务数据不会在应用启动时被重置或覆盖。

## 五、后端配置

开发机可使用默认配置；需要覆盖配置时，在启动前设置：

~~~powershell
$env:SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_URL = "jdbc:mysql://localhost:3306/carbon_emissions?useUnicode=true&characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci&serverTimezone=GMT%2B8"
$env:SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_USERNAME = "root"
$env:SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_PASSWORD = "替换为数据库密码"
$env:SPRING_DATA_REDIS_HOST = "localhost"
$env:SPRING_DATA_REDIS_PORT = "6379"
$env:CARBON_DB_URL = "jdbc:mysql://localhost:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8&useUnicode=true&connectionCollation=utf8mb4_unicode_ci"
$env:CARBON_DB_USERNAME = "root"
$env:CARBON_DB_PASSWORD = "替换为数据库密码"
$env:CARBON_STATISTICS_DEMO_ENABLED = "true"
$env:GOVIEW_AUDIT_SECRET = "三个后端共享的随机长字符串"
$env:CARBON_REPORT_RENDERER_ROOT = (Resolve-Path "carbon_report_agent").Path
$env:CARBON_REPORT_PYTHON = "python"
$env:ENERGY_PROJECT_ROOT = (Resolve-Path "energy_recovery_agent").Path
$env:ENERGY_PYTHON = "python"
$env:ENERGY_UPLOAD_DIR = (Join-Path (Resolve-Path ".").Path "uploadPath/energy")
~~~

报表导出还需要 `CARBON_REPORT_SOFFICE_PATH`。能耗优化数据库地址默认从主数据源配置推导，也可用 `ENERGY_DATABASE_URL` 显式设置。不要把真实密码和密钥写入 Git。

## 六、构建

后端构建（没有 mvnd 时将 mvnd 替换为 mvn）：

~~~powershell
mvnd -pl ruoyi-admin -am package -DskipTests
mvnd -f tpfhs-9/backend/pom.xml clean package -Dmaven.test.skip=true
mvnd -f goview/go-view-serve-master/pom.xml clean package -DskipTests
~~~

主后台已集成 `ruoyi-modules/ruoyi-single-train`，无需单独启动新的 Java 服务；单列车算法由主后台按 `SINGLE_TRAIN_WORKSPACE_ROOT` 和 `SINGLE_TRAIN_ALGORITHM_ROOT` 调用。

确认以下产物存在：

~~~text
ruoyi-admin/target/ruoyi-admin.jar
tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar
goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war
~~~

前端构建：

~~~powershell
cd ruoyi-ui
npm run build:prod
cd ..
cd tpfhs-9/frontend
npm run build
cd ../..
cd goview/go-view-master-fetch
$env:VITE_PRO_PATH = ""
pnpm build
cd ../..
~~~

## 七、启动本地全部模块

统一脚本启动 8081、8082、8083、8086、8090、80、5173、5177 和 3000：

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/start-local.ps1
~~~

日志位于 `.runtime/logs/start-时间戳/`。脚本优先使用 `PYTHON_PATH`，未设置时自动查找 `python.exe`，不依赖当前电脑的固定用户目录。

手动启动后端：

~~~powershell
java -jar ruoyi-admin/target/ruoyi-admin.jar --server.port=8081
java -jar tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar --spring.profiles.active=local --server.port=8082
java -jar goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war --server.port=8083
# 趋势预测还需要 railway_carbon_prediction/scripts/run_api.py（8090）和
# railway_carbon_prediction/railway_carbon_platform/backend（8086）。建议使用统一脚本启动。
~~~

## 八、本地验收

~~~powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 80,3000,5173,5177,8081,8082,8083,8086,8090 } |
  Select-Object LocalPort,OwningProcess

Invoke-WebRequest http://localhost/ -UseBasicParsing
Invoke-WebRequest http://localhost:5177/ -UseBasicParsing
Invoke-WebRequest http://localhost:8081/code -UseBasicParsing
Invoke-WebRequest http://localhost:8083/doc.html -UseBasicParsing
powershell -ExecutionPolicy Bypass -File tools/verify-data-persistence.ps1
~~~

未携带令牌访问受保护的模型接口返回 401 是正常的。登录后至少检查组织/人员/角色、采集点和人工采集权限、人工录入审核、报表导出、能耗项目运行记录以及 GoView 项目预览。前端或权限变更后使用 Ctrl+F5 并重新登录。

## 九、常见本地问题

- 端口占用：用 Get-NetTCPConnection 检查 80、3000、5177、8081、8082、8083，停止对应旧进程后再启动。
- 模型页面提示登录失效：确认 8081、8082、5177 使用同一份最新构建产物，清理缓存后重新登录。
- energy_run 不存在：执行 sql/carbon-energy/V1__energy_tables.sql 后重启主系统。
- 在线编辑页面提示 energy_version_edit_sheet 不存在：执行 sql/carbon-energy/V7__portable_energy_compatibility.sql 并重启主后端；当前版本也会在主后端启动时自动补齐该表。
- 报表失败：检查 Python 依赖、CARBON_REPORT_RENDERER_ROOT、LibreOffice 和 report-work/uploadPath/reports 写权限。
- GoView 无法跳转：确认 8083、3000 同时运行，且 GOVIEW_AUDIT_SECRET 在相关后端一致。
- 重启后数据为空：先确认连接的是原数据库和原数据目录；Docker 检查 `docker/mysql/data/`、`docker/web-screen/sqllite/` 是否仍被挂载，禁止用空目录或空数据库文件覆盖。
- 系统参数读取不稳定：执行 `sql/system_config_unique.sql`，然后运行 `tools/verify-data-persistence.ps1`，重复参数键必须为 0。

## 十、当前版本验收要点

本版本包含采集点树操作区的紧凑布局：加点、展开/折叠、上下移、删除、虚拟分摊和启用/停用均使用带悬浮提示的图标按钮，名称区域会优先保留显示空间。三个采集类型页面使用同一套按钮尺寸和间距。

本版本还包含以下数据一致性修复：

- 电表、化石燃料和外购热力采集点的 DQI A1/A2/A4 选择会写入数据库，并在关闭后重新打开时完整回显。
- 核算模版的“自动核算”默认关闭；只有显式勾选后才显示计划任务配置。未勾选时，到达计划时间或采集数据变化都不会自动发起核算。
- 核算模版可按归属公司设置“统计基准模版”。参数键为 `carbon.statistics.baseline-template.<公司部门ID>`，统计查询默认选中该模版，预测模块也应复用此键。
- 大屏统计兼容旧任务缺失的节点分类快照；历史汇总全为零但核算明细存在非零值时，使用真实核算明细恢复展示。

统计基准参数可直接核验：

~~~sql
SELECT config_key, config_name, config_value
FROM sys_config
WHERE config_key LIKE 'carbon.statistics.baseline-template.%';
~~~

启动后如果主页面连续提示“系统接口 500 异常”，优先检查 `8081` 是否监听。该提示通常表示主后端未启动，不是前端路由错误；直接执行以下脚本即可按统一配置补齐缺失模块：

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/start-local.ps1
Invoke-WebRequest http://localhost/dev-api/code -UseBasicParsing
~~~

验证码接口返回 `200` 即表示主后端和前端代理已恢复；未携带令牌访问用户信息接口返回 `401` 属于正常鉴权结果。服务器部署和更新请勿复制本节命令，按服务器专用说明执行。

服务器首次部署及已有服务器更新不在本文范围内，请按 [服务器部署与更新说明](server-update-instructions.md) 操作。
