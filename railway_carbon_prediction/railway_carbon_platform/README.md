# 铁路碳排放趋势预测平台模块

面向大平台的独立前端 + 后端模块，前端使用 Vue 3，后端使用 Spring Boot，数据与 Python 预测算法服务共用 `carbon_emissions` 数据库。

## 1. 模块定位

```text
Vue3 前端（左侧目录树）
        │  /api/platform/*
        ▼
Spring Boot 平台后端（本模块）
        │  JDBC
        ├──────────────► MySQL carbon_emissions
        │                  prediction_* 表
        │
        └── REST/JSON ──► Python FastAPI 预测算法服务
                           /api/v1/prediction/*
```

- **Spring Boot**：数据管理、异常审核、模型与任务查询、预测结果查询、平台 API。
- **Python FastAPI**：异常检测、因子解析、训练、预测、排放重算等算法能力。
- **Vue3**：左侧目录树、中文界面、表格/图表/表单。

## 2. 目录

```text
railway_carbon_platform/
├─ backend/                       Spring Boot 3.3 + Java 17
│  ├─ src/main/java/com/railway/carbon/platform/
│  │  ├─ common/                  统一响应、异常、分页
│  │  ├─ config/                  CORS、配置
│  │  ├─ controller/              REST API
│  │  ├─ dto/                     请求/响应 DTO
│  │  └─ service/                 JDBC 查询、Python 代理
│  ├─ src/main/resources/application.yml
│  └─ maven-settings.xml          本机 Maven 仓库设置（可按环境调整）
├─ frontend/                      Vue 3 + Vite + Element Plus + ECharts
│  ├─ src/layout/AppLayout.vue    左侧目录树布局
│  ├─ src/views/                  9 个业务页面
│  ├─ src/api/                    Axios API 封装
│  └─ src/utils/dict.js           编码→中文、标签颜色
└─ screenshots/                   页面截图（开发验证用）
```

## 3. 功能菜单

| 一级菜单   | 二级菜单        | 说明                                              |
| ------ | ----------- | ----------------------------------------------- |
| 数据管理   | 历史数据浏览      | 按组织/品种/月份/质量状态查询活动数据                            |
| 数据管理   | 新数据入库       | 手工录入、人工核实、提交后自动异常筛选                             |
| 数据管理   | 碳排放因子管理     | 排放因子版本、供热面积系数/电网因子                              |
| 数据管理   | 政策/外部因子月度数据 | 煤价、供给、运输、电力、气象、政策等                              |
| 数据管理   | 大事件日历表管理    | 春节、疫情、检修事件                                      |
| 异常数据管理 | 异常数据人工审核    | 待审核异常、证据查看、keep/correct/exclude/mark_breakpoint |
| 异常数据管理 | 历史异常数据浏览    | 复核级/关注级历史记录                                     |
| 模型管理   | 模型版本与训练     | 冠军模型、候选模型、指标、手动训练、任务进度                          |
| 碳排放预测  | 预测结果与历史数据   | 预测明细、趋势图、历史排放、API 说明                            |

## 4. 本地启动

### 4.1 前置条件

- JDK 17
- Maven 3.8+
- Node.js 18+
- MySQL 5.7+，库 `carbon_emissions` 已执行 `../sql/001_schema.sql`、`002_seed.sql`
- Python 预测服务依赖已安装，且可启动 FastAPI

### 4.2 启动 Python 算法服务

在项目根目录执行：

```powershell
$env:PYTHONPATH="$PWD\src"
python -m uvicorn carbon_prediction.api:app --host 127.0.0.1 --port 8090
```

### 4.3 启动 Spring Boot

```powershell
cd railway_carbon_platform\backend
mvn -s maven-settings.xml spring-boot:run
```

或先打包再运行：

```powershell
mvn -s maven-settings.xml -DskipTests package
java -jar target\carbon-platform-1.0.0.jar
```

默认端口 `8086`。数据库连接可用环境变量覆盖：

```text
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=carbon_emissions
DB_USER=root
DB_PASSWORD=123456
PREDICTION_BASE_URL=http://127.0.0.1:8090
PREDICTION_API_KEY=dev-key
```

### 4.4 启动 Vue 前端

```powershell
cd railway_carbon_platform\frontend
npm install
npm run dev
```

浏览器访问：<http://localhost:5173>

Vite 已配置 `/prediction-api` 代理到 `http://127.0.0.1:8086`。

### 4.5 生产构建

```powershell
cd railway_carbon_platform\frontend
npm run build
```

静态文件在 `frontend/dist`，由 Nginx 托管在 `/prediction/`，并将 `/prediction-api/` 反向代理到 Spring Boot。

## 5. 核心业务流

### 5.1 新数据入库

```text
手工录入 → 加入待入库列表 → 勾选“已人工核实” → 确认入库
  → Spring Boot 调 Python /ingest/monthly
  → Python 写 activity、解析因子、重算 emission、自动异常检测
  → 有异常：status=pending_review，activity.quality_status=pending
  → 人工审核：keep/correct/exclude/mark_breakpoint
  → Python 重算 emission、写审计、批次完成
```

> 入库前先校验因子覆盖；因子缺失/版本冲突会阻断入库，不会先写一半数据。

**重复入库保护**：

- 同组织同月已有活动数据时默认返回 `409`，不覆盖；
- 前端弹出“该月份已入库，确认覆盖？”对话框，必须填写覆盖原因；
- 覆盖时先写 `prediction_ingest_audit`：旧活动值、旧排放值、旧异常状态；
- 旧 `pending` 异常标记为 `rejected`，避免同一月重复待办；
- 同一 `idempotency_key` 对应不同请求体时返回 `409`，不会静默复用旧批次；
- 已有库执行 `../sql/005_ingest_guard_audit.sql` 增加字段和审计表。

**组织口径说明**：

- 机辆分公司（JLG）有货运周转量、牵引电力；2019—2023 历史缺失段按辅助用电占比拆分 `ELEC_TRAC/ELEC_AUX`，2024 年起使用实测值；
- **后续月度接入不再对机辆做牵引/辅助拆分**，数据源必须同时提供 `ELEC_TOTAL/ELEC_TRAC/ELEC_AUX`，并校验三者闭合；
- 肃宁（SNF）、原平（YPF）没有货运周转量和牵引电力，全部电力归辅助生产电力，即 `ELEC_AUX = ELEC_TOTAL`，不生成 `ELEC_TRAC` 记录；
- 前端品种下拉会按组织过滤：选择 SNF/YPF 时不显示“货运周转量”“牵引电力”；
- Python 入库接口对 SNF/YPF 的 `TURNOVER/ELEC_TRAC` 记录直接拒绝，避免再次产生错误推算；
- 已清洗的历史数据可执行 `../sql/004_fix_non_jlg_traction.sql` 复核。

### 5.2 异常审核

- 复核级：`prediction_anomaly`，进入人工审核队列；
- 关注级：`prediction_anomaly_watch`，只进入监控，不进审核队列；
- 审核通过后自动重算排放，历史结果保留。

### 5.3 模型训练

```text
前端“手动训练” → Spring Boot /models/train
  → Python /train 创建 job 并异步执行
  → 前端每 3 秒查询 /jobs/{job_id}
  → 成功后刷新模型列表
```

## 6. 主要 API

| 方法     | 路径                                    | 说明                       |
| ------ | ------------------------------------- | ------------------------ |
| GET    | `/api/platform/meta/all`              | 组织、品种字典                  |
| GET    | `/api/platform/activity`              | 活动数据分页                   |
| GET    | `/api/platform/energy/monthly`        | 指定分公司指定月份能耗查询            |
| GET    | `/api/platform/energy/compare`        | 比对提交值与库中能耗值（1/0/2）       |
| POST   | `/api/platform/activity/ingest`       | 新数据入库（代理 Python）         |
| GET    | `/api/platform/factors`               | 排放因子列表                   |
| POST   | `/api/platform/factors`               | 新增/更新排放因子                |
| GET    | `/api/platform/caliber-rules`         | 供热面积系数/电网因子              |
| POST   | `/api/platform/caliber-rules`         | 新增口径规则                   |
| GET    | `/api/platform/policy-factors`        | 政策/外部因子分页                |
| POST   | `/api/platform/policy-factors`        | 保存政策/外部因子                |
| GET    | `/api/platform/calendar-events`       | 日历事件                     |
| POST   | `/api/platform/calendar-events`       | 保存日历事件                   |
| DELETE | `/api/platform/calendar-events/{id}`  | 删除日历事件                   |
| GET    | `/api/platform/anomalies`             | 异常分页（scope=review/watch） |
| POST   | `/api/platform/anomalies/{id}/review` | 异常审核（代理 Python）          |
| GET    | `/api/platform/models`                | 模型列表                     |
| DELETE | `/api/platform/models/{modelId}`      | 删除已弃用模型（无预测引用）          |
| POST   | `/api/platform/models/train`          | 提交训练（代理 Python）          |
| GET    | `/api/platform/jobs`                  | 任务列表                     |
| GET    | `/api/platform/jobs/{id}`             | 任务详情（代理 Python）          |
| GET    | `/api/platform/forecast`              | 未来 12 月预测                |
| GET    | `/api/platform/history`               | 历史月度排放                   |
| POST   | `/api/platform/forecast/generate`     | 重新生成预测（代理 Python）        |
| GET    | `/api/platform/dashboard`             | 看板汇总                     |
| GET    | `/api/platform/api-info`              | 对外 API 清单                |

统一响应：

```json
{"code": 0, "message": "ok", "data": {}}
```

## 7. 中文显示约定

- 组织、品种由后端返回 `orgName/varName`；
- 质量状态、异常等级/类别/状态、模型类型/状态、任务状态、情景、事件类型等在前端 `src/utils/dict.js` 统一映射；
- 原始编码仅作为接口字段，不直接展示给用户。

## 8. 当前验证

- Spring Boot `mvn -DskipTests package` 通过；
- Vue `npm run build` 通过；
- 后端接口冒烟：meta/activity/factors/caliber-rules/policy-factors/calendar/anomalies/models/jobs/forecast/history/dashboard/api-info 均返回 `code=0`；
- 页面截图见 `screenshots/`。

> 说明：异常审核、训练、预测、新数据入库依赖 Python FastAPI 服务；只启动 Spring Boot 时，查询类页面可用，写操作会提示“预测算法服务不可用”。
