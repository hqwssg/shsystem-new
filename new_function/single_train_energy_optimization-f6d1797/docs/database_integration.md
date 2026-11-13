# 数据库接入说明（单列车再生制动能量回收）

> 本文说明本项目如何把「读 CSV/JSON 文件」改为「从数据库读输入、把结果写回数据库」，
> 以及改造后哪些性质**必须保持不变**。全链路已在真实 PostgreSQL 16.2 上跑通，
> 库模式与文件模式读数逐位一致（见第 7 节）。
>
> 对齐对象：同仓库 `heavy_empty_train_coordination` 的数据库方案（PostgreSQL + 不可变版本 + 原始字节留档 + 结果事务写回）。

## 1. 一句话结论

输入与结果已改为走 PostgreSQL；**算法数值逻辑一行未改**——数据库只做输入渠道与结果仓库，
装配前后走同一个 `build_component_bundle()`，因此同一版本、同一场景、同一控制器必须给出逐位相同的读数。

## 2. 改造范围

| 环节 | 改造前 | 改造后 |
| --- | --- | --- |
| 参数输入 | 读 `data/single_train/*.json` | 读 `single_train_parameter`（+ `single_train_dataset_file` 里的原始字节） |
| 共享铁路数据 | 读同级项目的 CSV | 读同一张 `dataset_file` 表里留档的字节 |
| 结果输出 | 写 `summary.csv` / NPZ / JSON | 写 `single_train_run_result` + `result_artifact` |
| 文件模式 | 唯一入口 | **保留**，作为回归对照与离线复算入口 |

没有做的部分（按需求范围）：worker 租约与心跳、多角色权限、平台任务队列。当前是「单进程直连库」的轻量形态。

## 3. 目录与表结构

代码位置：`regenerative_braking/database/`

```
database/
├── connection.py      连接、事务、脚本执行（psycopg 延迟导入）
├── migrations.py      迁移发现/执行/校验和比对
├── migrations/        001_core.sql、002_runs.sql
├── projection.py      参数行 <-> payload、结果行
├── repository.py      仓储：版本导入、输入读回、运行与结果写入
├── loader.py          从库装配算法输入（与文件模式等价）
└── cli.py             命令行：migrate / import-data / run / query / export-input
```

数据库：PostgreSQL 16+，schema `single_train_energy`，9 张表。

| 表 | 作用 | 关键点 |
| --- | --- | --- |
| `single_train_schema_migration` | 迁移记录 | 校验和不同即拒绝，防止库与代码悄悄漂移 |
| `single_train_project` | 项目 | 一项目一行（默认 `single-train-energy`） |
| `single_train_version` | 输入版本 | **发布后不可覆盖**；改数据即新版本 |
| `single_train_dataset_file` | 源文件原始字节 | 参数 JSON 与共享铁路 CSV 全量留档 + SHA-256 |
| `single_train_parameter` | 参数投影 | 64 个数值字段逐行；带单位、中文名、溯源、等级 |
| `single_train_scenario` | 场景元数据 | 14 档的 id/变体/族/步数；剖面由代码与线路数据重建，不入库 |
| `single_train_run` | 一次运行 | 幂等键 + 请求摘要；状态 `running/succeeded/failed` |
| `single_train_run_result` | 结果核心列 | 能量台账 + 门禁字段列化；完整台账/指标存 jsonb |
| `single_train_result_artifact` | 完整产物 | 时序 CSV、摘要 JSON 按字节保存 + SHA-256 |

## 4. 三条设计决定及其理由

**① 原始字节是输入真源，参数表只是投影。**
参数文件里不只有数值——`basic_resistance.basis` 决定基本阻力走哪个公式分支，
`topology`、`modes.*` 等也是配置。只投影数值字段会让这些文本配置在往返中丢失，
装配结果就可能悄悄变化。所以读回时以 `dataset_file` 的原始 payload 打底，参数行覆盖数值。

**② 参数表存溯源原文，不存改写的展示文案。**
`provenance` 列存文件里的原话，保证「库 → payload」与「文件 → payload」逐字段相同；
给界面看的工程表述由 `parameter_glossary.display_text()` 现算。两者混用会导致审计对不上。

**③ 逐拍时序不进关系表。**
单场景 80 000 拍 × 31 列，全矩阵（14 档 × 9 控制器）达亿级行，检索价值低而存储成本高。
按 artifact 存字节，需要时还原——与重空协同的处理一致。

## 5. 部署与使用

```bash
# 1. 装依赖
python -m pip install -r requirements-database.txt

# 2. 配置连接串（不要写进仓库）
export SINGLE_TRAIN_DATABASE_URL="postgresql://user:pass@host:5432/dbname"

# 3. 建 schema 与表
python -m regenerative_braking.database.cli migrate

# 4. 导入一版输入（参数 JSON + 共享铁路数据 + 14 档场景元数据）
python -m regenerative_braking.database.cli import-data \
    --version-code v2026-11 --data-status placeholder \
    --source-note "正式硬件参数到位前的规划版本"

# 5. 跑一个场景并写库
python -m regenerative_braking.database.cli run \
    --version-code v2026-11 --scenario s1_flat_braking --controller rhonn_nsmc

# 6. 查结果
python -m regenerative_braking.database.cli query --version-code v2026-11

# 7. 把库中版本还原成文件（审计 / 与文件模式对拍）
python -m regenerative_braking.database.cli export-input \
    --version-code v2026-11 --out verify/exported
```

Python 侧：

```python
from regenerative_braking.database.loader import load_inputs_from_database

inputs = load_inputs_from_database("single-train-energy", "v2026-11")
bundle, shared = inputs.bundle, inputs.shared      # 与 load_component_bundle() 的产物同类型
```

## 6. 行为不变的三条硬约束

1. **版本不可覆盖**：同 `version_code` 内容变了，直接报错并提示换版本号。
2. **运行幂等**：同幂等键同内容返回已有运行；同键异内容拒绝（防止静默复用错误结果）。
3. **结果单事务**：run、result、artifact 一起成功或一起回滚；不会出现「状态成功但结果只写一半」。

## 7. 验证状态

端到端「建表 → 导入 → 运行 → 读数比对」**已在真实 PostgreSQL 16.2 上执行并闭合**，
且库模式与文件模式的读数逐位相同。

本地验证实例的搭建方式（免安装、不写注册表、不影响系统）：

```bash
# 1) 准备二进制（只需一次）。PG 是独立进程，用哪个 Python 版本装 pgserver 都行，
#    项目 venv 只用 psycopg 连它，不需要装 pgserver
py -3.12 -m venv ~/.workbuddy/binaries/pgenv
~/.workbuddy/binaries/pgenv/Scripts/python -m pip install pgserver

# 2) 起实例（前台占用终端，Ctrl+C 停止；首次会自动 initdb）
python tools/dev_postgres.py start --port 5433

# 3) 另开终端跑数据库命令
export SINGLE_TRAIN_DATABASE_URL="postgresql://postgres:@127.0.0.1:5433/postgres"
python -m regenerative_braking.database.cli migrate
```

已验证项：

| 验证项 | 方式 | 结果 |
| --- | --- | --- |
| 迁移建表 | 真实 PG 执行 `001` / `002` | 9 张表、95 列、迁移记录齐全 |
| 迁移幂等 | 连续两次 `migrate` | 第二次 `applied == []` |
| 参数导入 | `import-data` 导一版 | 64 个字段、`dc_dc` 20 / `motor` 13 / `storage` 12 / `train` 19 |
| 参数溯源落库 | 统计 `provenance IS NOT NULL` | 61 / 61 全部有溯源 |
| 中文名落库 | `field_path = 'inductance_h'` | `滤波电感` |
| 共享数据留档 | `dataset_file` | 13 行（4 参数 + 9 共享） |
| 场景登记 | `scenario` | 14 档（含族 R） |
| 结果写库 | `run` / `run_result` / `result_artifact` | `status = succeeded`，时序 CSV 3.92 MB + summary JSON 5.6 KB |
| **端到端读数一致** | `s1_flat_braking` 80 000 拍 | 台账 32 项 + 指标 79 项**逐位相同**；净存入 `4.146679 kWh`、端口吸收 `4.370983`、峰值 `1134.6805 V`、闭合 `2.084e-06` |
| **端到端读数一致** | `s2_long_downhill` 57 038 拍 | 台账 32 项 + 指标 79 项**逐位相同**；净存入 `2.956285 kWh`、闭合 `1.825e-06` |
| 运行幂等 | 同参数重跑 | 返回同一 `run_id`，`run` 表未新增行 |
| 库 → 文件往返 | `export-input` 导出后与原 JSON 比对 | 4 个文件全部 `==` |
| 只读约束 | 只读连接执行 DDL | `default_transaction_read_only = on`，抛 `ReadOnlySqlTransaction` |
| 集成测试 | `tests/test_database_integration.py` | 5 项通过（无 DSN 时整体 skip） |
| 离线契约测试 | `tests/test_database_contract.py`、`test_database_bundle_equivalence.py` | 31 项通过 |

### 7.1 上真实库后才暴露的问题（已修复）

这三处纯离线测试覆盖不到——`pglast` 能校验 SQL 语法，但校验不了驱动 API 与连接语义：

| 问题 | 现象 | 修法 |
| --- | --- | --- |
| `ClientCursor` 构造方式用了 psycopg2 写法 | `cursor(cursor_factory=...)` 在 psycopg3 上抛 `TypeError`，迁移完全跑不动 | 改为 `ClientCursor(connection)` 直接实例化 |
| 只读查询强制要求第二个环境变量 | 只配 `SINGLE_TRAIN_DATABASE_URL` 时 `query` 直接拒绝服务 | 只读时优先 `SINGLE_TRAIN_READONLY_DATABASE_URL`，缺失则回落主连接串 |
| `readonly` 只换连接串、不禁写 | 名为只读却能提交写操作 | 连接上带 `-c default_transaction_read_only=on`，由服务端拒绝写入 |

这三条说明一件事：**SQL 语法正确 ≠ 能跑**。往后新增数据库相关代码，必须在这套真实库上过一遍。

## 8. 与文件模式的关系

文件模式没有下线，两者的分工：

| 场景 | 用哪个 |
| --- | --- |
| 日常回归、离线复算 | 文件模式（`load_component_bundle()`） |
| 平台接入、结果留档、版本追溯 | 数据库模式 |
| 改动后的对拍 | 两套都跑，比读数 |

`regenerative_braking/simulation/scenario_runner.py` 里：
`load_component_bundle()` 负责从文件取参数，`build_component_bundle(parameters, paths)` 负责装配。
数据库路径走后者，所以装配规则只有一份。
