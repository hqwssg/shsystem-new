# 朔黄碳排放系统部署指南

本文用于在另一台 Windows 或 Linux 电脑上部署当前项目。项目包含主系统、碳排放模型、GoView 大屏和两个独立前端。首次部署建议使用 Docker；开发调试使用源码部署。

## 1. 服务和端口

| 服务 | 作用 | 源码端口 | Docker 对外端口 |
| --- | --- | ---: | ---: |
| `ruoyi-admin` | 主系统、权限、采集、报表、能量模块 API | 8081 | 80（Nginx 代理） |
| `tpfhs-9/backend` | 碳排放核算和人工数据 API | 8082 | 主 Web 容器代理 |
| `tpfhs-9/frontend` | 碳排放模型前端 | 5177 | 主 Web 容器代理 |
| GoView 后端 | 大屏项目和用户数据 | 8083 | 大屏容器代理 |
| GoView 前端 | 大屏编辑和预览 | 3000 | 3000 |
| MySQL | `carbon_emissions` 业务库 | 3306 | 3306 |
| Redis | 登录、缓存和任务运行时 | 6379 | 主 Web 容器内部 |

源码运行时主系统前端通常为 `http://localhost/`，GoView 为 `http://localhost:3000/`。

## 2. 交付文件

必须保留以下源码目录和文件：

```text
pom.xml
ruoyi-admin/ ruoyi-auth/ ruoyi-api/ ruoyi-common/ ruoyi-modules/
ruoyi-ui/
tpfhs-9/backend/ tpfhs-9/frontend/
goview/go-view-serve-master/ goview/go-view-master-fetch/
carbon_report_agent/
sql/ schema_1.sql docker/
```

数据库初始化至少需要：

```text
sql/carbon_emissions.sql
sql/logging_migration.sql
schema_1.sql
sql/carbon-report/V1__report_tables.sql
sql/carbon-report/V11__shuohuang_project_integration.sql
sql/carbon_permission_model.sql
sql/carbon_collection_scope_permissions.sql
sql/carbon-energy/V1__energy_tables.sql
sql/carbon-energy/V2__menus.sql
```

报表生成必须保留 `carbon_report_agent/` 及其模板、图片和字体资源。要保留已有 GoView 大屏、用户和项目，必须保留：

```text
goview/go-view-serve-master/sqllite/goview.db
goview/upload/
```

源码交付时可以不带 `**/node_modules`、`**/target`、`**/dist`、`.git`、`logs`、`report-work` 和临时上传文件。Docker 成品交付时则必须保留 `docker/web-main`、`docker/web-screen` 中生成的 JAR/WAR、前端 `dist`、Python 模块、SQLite 数据库和上传目录。

## 3. 环境要求

源码部署需要：

- JDK 17：主系统和碳排放模型。
- JDK 8：GoView 后端。可与 JDK 17 并存，构建 GoView 时切换 `JAVA_HOME`。
- Maven 3.8+（或仓库使用的 Maven Daemon）。
- Node.js 18/20、npm；GoView 推荐 pnpm 9+。
- Python 3.10+、pip、LibreOffice Writer 和中文字体。
- MySQL 5.7/8.0（`utf8mb4`）和 Redis 6+。

Docker 部署只需要 Docker Engine、Docker Compose 和能够下载镜像/依赖的网络。Dockerfile 已安装 Java、Nginx、Redis、Python、LibreOffice 和中文字体。

## 4. 源码部署（Windows）

以下命令在仓库根目录执行，建议将仓库放在不含空格和中文的路径。

### 4.1 获取代码和检查工具

```powershell
git clone https://github.com/hqwssg/shuohuang.git
cd shuohuang
java -version
mvn -version
node -v
npm -v
python --version
mysql --version
redis-server --version
```

### 4.2 初始化 MySQL

先启动 MySQL 和 Redis。全新数据库执行基础脚本：

```powershell
mysql -uroot -p < sql/carbon_emissions.sql
```

然后执行增量脚本：

```powershell
mysql -uroot -p carbon_emissions < sql/logging_migration.sql
mysql -uroot -p carbon_emissions < schema_1.sql
mysql -uroot -p carbon_emissions < sql/carbon-report/V1__report_tables.sql
mysql -uroot -p carbon_emissions < sql/carbon-report/V11__shuohuang_project_integration.sql
mysql -uroot -p carbon_emissions < sql/carbon_permission_model.sql
mysql -uroot -p carbon_emissions < sql/carbon_collection_scope_permissions.sql
mysql -uroot -p carbon_emissions < sql/carbon-energy/V1__energy_tables.sql
mysql -uroot -p carbon_emissions < sql/carbon-energy/V2__menus.sql
```

`carbon_emissions.sql` 会删除并重建基础表，只能用于全新数据库。已有生产库不要重新执行它，应先备份后按需执行增量脚本。没有 `V1__energy_tables.sql` 时，主系统启动恢复任务会因缺少 `energy_run` 表退出。

### 4.3 配置主系统

编辑 `ruoyi-admin/src/main/resources/application.yml`，确认 MySQL、Redis 和上传目录。生产环境建议使用环境变量覆盖密码：

```powershell
$env:SERVER_PORT = "8081"
$env:SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_URL = "jdbc:mysql://localhost:3306/carbon_emissions?useUnicode=true&characterEncoding=utf8&serverTimezone=GMT%2B8"
$env:SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_USERNAME = "root"
$env:SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_PASSWORD = "数据库密码"
$env:SPRING_DATA_REDIS_HOST = "localhost"
$env:GOVIEW_AUDIT_SECRET = "随机长字符串"
$env:CARBON_REPORT_RENDERER_ROOT = (Resolve-Path "carbon_report_agent").Path
$env:CARBON_REPORT_PYTHON = "python"
$env:ENERGY_PROJECT_ROOT = "D:\energy_recovery_agent"
```

`ENERGY_PROJECT_ROOT` 仅在执行真实能量优化时必填；列表和页面接口不依赖它。

### 4.4 安装报表 Python 依赖

```powershell
python -m venv .venv-report
.\.venv-report\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r docker/web-main/requirements-cli.txt
```

没有 LibreOffice 时请安装，并将 `CARBON_REPORT_SOFFICE_PATH` 指向 `soffice.exe`。Linux 通常为 `/usr/bin/libreoffice`。

### 4.5 构建后端

```powershell
# 主系统，包含 report、energy 等模块
mvn -pl ruoyi-admin -am -DskipTests package

# 碳排放模型
mvn -f tpfhs-9/backend/pom.xml clean package -DskipTests

# GoView：切换 JAVA_HOME 到 JDK 8 后执行
mvn -f goview/go-view-serve-master/pom.xml clean package -DskipTests
```

产物分别为：

```text
ruoyi-admin/target/ruoyi-admin.jar
tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar
goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war
```

### 4.6 构建前端

```powershell
cd ruoyi-ui
npm ci
npm run build:prod
cd ..

cd tpfhs-9/frontend
npm ci
npm run build
cd ../..

cd goview/go-view-master-fetch
corepack enable
pnpm install --frozen-lockfile
Copy-Item .env.example .env
pnpm build
cd ../..
```

开发模式分别执行 `npm run dev`、`npm run dev` 和 `pnpm dev`。主系统默认端口 80，模型前端为 5177，GoView 为 3000。GoView `.env` 的 `VITE_DEV_PATH` 应指向 `http://localhost:8083`。

### 4.7 配置 GoView 数据

保留 `goview/go-view-serve-master/sqllite/goview.db`。如果换了目录，用环境变量覆盖：

```powershell
$env:GOVIEW_DB_URL = "jdbc:sqlite:D:/apps/shuohuang/goview/go-view-serve-master/sqllite/goview.db"
$env:GOVIEW_UPLOAD_MAPPING = "file:D:/apps/shuohuang/goview/upload/"
$env:GOVIEW_UPLOAD_PATH = "D:/apps/shuohuang/goview/upload"
```

### 4.8 启动顺序

先启动 MySQL、Redis，再启动三个 Java 服务：

```powershell
java -jar ruoyi-admin/target/ruoyi-admin.jar
java -jar tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar
java -jar goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war
```

另开终端启动前端开发服务器：

```powershell
cd ruoyi-ui; npm run dev
cd tpfhs-9/frontend; npm run dev
cd goview/go-view-master-fetch; pnpm dev
```

验证地址：

```text
主系统 API：http://localhost:8081
模型前端：http://localhost:5177
模型 API：http://localhost:8082
GoView：http://localhost:3000
GoView API 文档：http://localhost:8083/doc.html
```

未登录访问 `/carbon/energy/runs` 返回 401 是正常鉴权结果；不应再返回 `No static resource carbon/energy/runs`。

## 5. Docker 部署（推荐）

先完成源码构建，再在 Linux、WSL 或 Git Bash 中执行：

```bash
cd docker
sh copy.sh
export GOVIEW_AUDIT_SECRET="随机长字符串"
docker compose up -d ruoyi-db
docker compose up -d ruoyi-web ruoyi-screen
docker compose ps
```

`copy.sh` 会复制三个后端产物、三个前端产物、报表 Python 模块、GoView SQLite 数据库、上传资源和所有初始化 SQL，其中包括 `zz05_energy_tables.sql`、`zz06_energy_menus.sql`。

启动数据库并等待初始化完成：

`docker logs -f ruoyi-db`

`docker exec ruoyi-db mysql -uroot -ppassword carbon_emissions -e "SHOW TABLES LIKE 'energy_run';"`

默认 Docker MySQL root 密码为 `password`。生产环境必须修改密码、`GOVIEW_AUDIT_SECRET` 和前端公开地址。

需要持久化和备份的目录：

```text
docker/mysql/data/
docker/web-main/uploadPath/
docker/web-main/redis-data/
docker/web-screen/sqllite/
docker/web-screen/upload/
```

不要在生产环境使用 `docker compose down -v`，否则会删除数据库数据。

## 6. 关键环境变量

| 变量 | 用途 |
| --- | --- |
| `SERVER_PORT` | 主系统端口，默认 8081 |
| `SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_URL/USERNAME/PASSWORD` | 主系统 MySQL |
| `SPRING_DATA_REDIS_HOST/PORT` | Redis 地址 |
| `CARBON_DB_URL/USERNAME/PASSWORD` | 碳排放模型数据库 |
| `CARBON_REPORT_PYTHON` | 报表 Python 可执行文件 |
| `CARBON_REPORT_RENDERER_ROOT` | `carbon_report_agent` 所在目录 |
| `CARBON_REPORT_SOFFICE_PATH` | LibreOffice 路径 |
| `ENERGY_PROJECT_ROOT` | 能量求解器目录 |
| `GOVIEW_DB_URL` | GoView SQLite JDBC 地址 |
| `GOVIEW_AUDIT_SECRET` | 主系统、模型和 GoView 必须一致的审计密钥 |

## 7. 常见问题和验收

1. **能量接口 404**：确认请求发到 8081，且运行的是重新构建的 `ruoyi-admin.jar`；确认组件扫描包含 `com.ruoyi.carbon.energy`。
2. **`energy_run doesn't exist`**：执行 `sql/carbon-energy/V1__energy_tables.sql`，Docker 则检查 `docker/mysql/db/zz05_energy_tables.sql`。
3. **报表导出失败**：检查 Python 依赖、`CARBON_REPORT_RENDERER_ROOT`、LibreOffice 和中文字体。
4. **GoView 图片或登录失败**：检查 SQLite 绝对路径、`upload` 目录、`VITE_DEV_PATH` 和审计密钥。
5. **端口冲突**：同时修改后端端口和对应前端代理，不能只修改其中一处。
6. **生产库升级**：先备份 MySQL 和 SQLite，再执行增量 SQL；不要重复导入会 `DROP TABLE` 的 `carbon_emissions.sql`。

最低验收命令：

```powershell
Test-NetConnection localhost -Port 3306
Test-NetConnection localhost -Port 6379
Invoke-WebRequest http://localhost:8081/actuator/health
Invoke-WebRequest http://localhost:8082/actuator/health
Invoke-WebRequest http://localhost:8083/doc.html
```

登录后再验证组织/人员、采集点、人工录入、审核、报表和能量页面。
