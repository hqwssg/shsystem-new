# 朔黄铁路碳排放管理系统

本项目是基于 RuoYi 单体后端、碳排放核算模型和 GoView 大屏整合的综合系统，包含能耗数据采集、人工录入与审核、碳排放核算、报表生成、能量优化和可视化大屏。

项目仓库：<https://github.com/hqwssg/shuohuang>

## 功能模块

- 主系统：组织、人员、角色、菜单、采集点、自动/人工采集、数据审核和系统参数。
- 碳排放模型：能源数据、排放因子、核算模板、人工数据录入和核算结果。
- 报表模块：碳排放报告生成、校验、Word/PDF 导出和审计记录。
- 能量模块：能量项目、版本、运行任务、结果摘要和优化接口。
- GoView 大屏：项目管理、仪表盘编辑、朔黄铁路碳排放全景大屏和资源上传。

## 运行架构

| 服务 | 作用 | 默认端口 |
| --- | --- | ---: |
| `ruoyi-admin` | 主系统 API，包含认证、系统、报表和能量模块 | 8081 |
| `tpfhs-9/backend` | 碳排放核算模型 API | 8082 |
| `tpfhs-9/frontend` | 碳排放模型前端 | 5177 |
| GoView 后端 | 大屏项目和用户 API | 8083 |
| GoView 前端 | 大屏编辑和预览 | 3000 |
| MySQL | `carbon_emissions` 业务数据库 | 3306 |
| Redis | 登录、缓存和任务运行时 | 6379 |

主系统后端是单体启动方式，只需要启动 `ruoyi-admin`，不需要启动网关、Nacos、Sentinel 或 Seata。

## 目录说明

```text
ruoyi-admin/                         主系统启动模块
ruoyi-auth/ ruoyi-api/ ruoyi-common/ 公共、认证和内部接口模块
ruoyi-modules/                      system、gen、job、file、report、energy
ruoyi-ui/                            主系统 Vue 2 前端
tpfhs-9/backend/                     碳排放模型 Java 后端
tpfhs-9/frontend/                    碳排放模型 Vue 3 前端
goview/go-view-serve-master/         GoView Java 后端和 SQLite 数据库
goview/go-view-master-fetch/         GoView Vue 3 前端
carbon_report_agent/                 报表 Python 渲染模块
sql/                                 基础库和增量迁移脚本
docker/                              Docker 构建和部署文件
```

## 快速启动

先准备 Java 17、Java 8（GoView）、Maven、Node.js、pnpm、Python、MySQL 和 Redis。全新数据库先导入 `sql/carbon_emissions.sql`，再按部署文档执行增量 SQL。

构建后端：

```powershell
mvn -pl ruoyi-admin -am -DskipTests package
mvn -f tpfhs-9/backend/pom.xml clean package -DskipTests
# 使用 JDK 8 构建 GoView
mvn -f goview/go-view-serve-master/pom.xml clean package -DskipTests
```

构建前端：

```powershell
cd ruoyi-ui; npm ci; npm run build:prod; cd ..
cd tpfhs-9/frontend; npm ci; npm run build; cd ../..
cd goview/go-view-master-fetch; corepack enable; pnpm install --frozen-lockfile; pnpm build; cd ../..
```

启动顺序：MySQL/Redis → `ruoyi-admin` → 碳排放模型后端 → GoView 后端 → 前端。

```powershell
java -jar ruoyi-admin/target/ruoyi-admin.jar
java -jar tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar
java -jar goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war
```

## Docker 启动

源码构建完成后执行：

```bash
cd docker
sh copy.sh
export GOVIEW_AUDIT_SECRET="请替换为随机长字符串"
docker compose up -d ruoyi-db
docker compose up -d ruoyi-web ruoyi-screen
docker compose ps
```

`copy.sh` 会复制三个后端产物、三个前端产物、报表 Python 模块、GoView SQLite 数据库、上传资源以及能量/报表/权限 SQL。首次初始化数据库时才会自动执行这些 SQL。

## 数据库注意事项

- `sql/carbon_emissions.sql` 是全新数据库基础脚本，包含 `DROP TABLE`，不要在生产库重复执行。
- `schema_1.sql` 是采集点和碳排放业务补充脚本，不替代基础脚本。
- `sql/carbon-report/`、`sql/carbon-energy/` 和 `sql/carbon_*permission*.sql` 是功能增量迁移。
- 生产升级前必须备份 MySQL 和 `goview.db`。

## 重要环境变量

```text
SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_URL/USERNAME/PASSWORD
SPRING_DATA_REDIS_HOST/PORT
CARBON_DB_URL/USERNAME/PASSWORD
CARBON_REPORT_PYTHON
CARBON_REPORT_RENDERER_ROOT
CARBON_REPORT_SOFFICE_PATH
ENERGY_PROJECT_ROOT
GOVIEW_DB_URL
GOVIEW_AUDIT_SECRET
```

`GOVIEW_AUDIT_SECRET` 在主系统、碳排放模型和 GoView 中必须保持一致。`ENERGY_PROJECT_ROOT` 仅在执行真实能量优化时需要配置。

## 完整部署文档

详细的依赖安装、Windows/Linux 源码部署、Docker 部署、数据库迁移、端口配置、故障排查和验收步骤见：[docs/deployment-guide.md](docs/deployment-guide.md)。

## 默认访问地址

```text
主系统开发前端：http://localhost/
碳排放模型前端：http://localhost:5177/
GoView：http://localhost:3000/
GoView API 文档：http://localhost:8083/doc.html
```
