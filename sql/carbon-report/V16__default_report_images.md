# 默认报告图初始化（写入 MySQL）

补丁包内 **`files/carbon_report_agent/assets/suning/`** 与 **`sql/初始化-肃宁默认报告图.sql`** 是同一套三张图（封面、组织机构图、机关所在地）。整合方应**至少执行其一**把图片放进库；推荐 **SQL 初始化**，不依赖首次启动 Java。

## 何时执行

1. 已确认 [`检查-V15-是否已执行.sql`](检查-V15-是否已执行.sql) 三项均为 1（存在 `content` 列与 `default_slot`）。
2. 库中已有 `report_dept_profile`，且 **`entity_code = 'suning'`** 的部门（shsystem 标准种子一般为 **dept_id = 301**）。若查不到 suning 部门，脚本会跳过插入并提示 `WARN`。

## 操作步骤（给 AI / DBA）

```bash
# 示例：本机 MySQL
mysql -uroot -p --default-character-set=utf8mb4 carbon_emissions < sql/初始化-肃宁默认报告图.sql
```

或在客户端中打开 `sql/初始化-肃宁默认报告图.sql` 整段执行。

## 脚本行为

- 对 `cover_logo`、`org_chart`、`office_location` 各插入一行：`kind = 'default'`，`content` 为 LONGBLOB。
- **幂等**：该部门该 role 已有 `default` 行时**不会重复插入**（与启动时 `ReportDefaultImageSeeder` 逻辑一致）。
- 末尾 `SELECT` 应看到三行，且 `content_bytes` 与 `size_bytes` 一致（约 10016 / 127292 / 220004）。

## 与 Java Seeder 的关系

- 已用本 SQL 初始化后，启动 `ruoyi-admin` 时 Seeder 检测到已有默认图，**不会覆盖**。
- 若未跑 SQL，但配置了 `CARBON_REPORT_RENDERER_ROOT` 且 assets 在磁盘上，Seeder 仍可在首次启动时写入（二选一即可，**建议 SQL 以便验收明确**）。

## 验收

- 接口：`GET /carbon/report/default-images/cover_logo`（登录后）应 200 且能预览。
- 预检：报告校验不应出现「已配置但图片内容读不出来」（在已应用本补丁代码的前提下）。
