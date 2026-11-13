# 正式数据到件自动触发流程

本流程用于甲方正式数据交付后的无人值守接入。它只读取交付目录，并把通过完整性核验的内容冻结到独立快照；不会覆盖 `data/real_shuohuang/`、`data/source/` 或甲方原始文件。

## 1. 触发边界

唯一触发信号是交付包根目录中的 `OFFICIAL_DATA_READY.json`。数据提供方或接入人员必须先复制全部文件，最后再生成该标记。只有目录中的实际文件集合、文件大小和逐文件 SHA-256 与标记完全一致时，算法才会启动，因而不会读取仍在复制的半包数据。

推荐交付结构：

```text
data/official_inbox/delivery_20260909_01/
  converted_runtime/       # 已转换的算法运行时表
  source/                  # 经审查的来源文件和来源说明
  timetable.xlsx           # 已转换的正式运行图
  calibration/             # 可选，校准质量摘要
  OFFICIAL_DATA_READY.json # 最后生成
```

一个包对应一个冻结的数据版本和评价窗口。原始资料若仍需人工字段映射或格式转换，不应提前生成标记。

## 2. 生成最终标记

文件复制和转换完成后运行：

```powershell
python run_project.py create-official-data-marker `
  --package-dir data/official_inbox/delivery_20260909_01 `
  --delivery-id delivery_20260909_01 `
  --data-dir converted_runtime `
  --source-dir source `
  --timetable timetable.xlsx `
  --window-id 2026-09-09
```

如要求校准质量同时通过，追加：

```powershell
--calibration-summary calibration/pipeline_summary.json --require-calibration
```

标记还会冻结随机种子、结算时间步长、运行图允许调整范围及搜索规模。文件发生任何变化后必须重新生成标记，并使用新的 `delivery_id`。

## 3. 自动处理

平台或计划任务可每次执行一次：

```powershell
python run_project.py official-data-auto-trigger `
  --package-dir data/official_inbox/delivery_20260909_01 `
  --output-root outputs/official_data_auto_trigger
```

也可启动常驻轮询：

```powershell
python run_project.py official-data-auto-trigger `
  --package-dir data/official_inbox/delivery_20260909_01 `
  --output-root outputs/official_data_auto_trigger `
  --watch --poll-seconds 30
```

处理顺序固定为：

1. 核验标记结构、引用路径、精确文件集合、大小和 SHA-256；
2. 按交付指纹冻结只读输入快照，并对快照二次核验；
3. 执行严格正式数据验收；
4. 执行完整 `simulate --require-official-data` 和结果质量审计；
5. 执行现行运行图基线、无储能消融、规则优化、多种子 NSGA-II、时间步长敏感性及逐方案质量审计；
6. 写入处理账本和本次触发结果。

同一标记指纹无论上次结果是成功、门禁阻断还是执行失败，默认都不会重复运行。人工排除环境性故障后可用 `--retry` 新建下一次尝试目录；数据内容有变化时应生成新标记，而不是强制重试旧指纹。

## 4. 输出和状态

| 输出 | 用途 |
| --- | --- |
| `trigger_state.json` | 全部交付指纹、尝试次数、最终状态和结果目录的持久账本 |
| `latest_trigger_summary.json` | 平台界面或监控程序读取的最近一次检查结果 |
| `deliveries/<交付号-指纹>/snapshot/` | 通过哈希核验的冻结输入快照 |
| `runs/attempt_NNN/project_validation/` | 正式验收、完整仿真和结果质量审计 |
| `runs/attempt_NNN/formal_experiment/` | 基线、消融、优化、敏感性和汇总结果 |
| `runs/attempt_NNN/trigger_summary.json` | 本次尝试的机器可读结果 |

状态含义：

| 状态 | 含义 | 是否运行算法 |
| --- | --- | --- |
| `waiting` | 尚无最终标记 | 否 |
| `invalid` | 标记、路径、文件集合或哈希错误 | 否 |
| `duplicate` | 此指纹已经处理 | 否 |
| `busy` | 另一个触发进程持有互斥锁 | 否 |
| `blocked` | 正式数据或校准门禁未通过 | 否，或仅完成门禁前步骤 |
| `failed` | 仿真、质量审计或实验执行失败 | 视失败阶段而定 |
| `completed` | 工程主链和正式对比总控全部通过 | 是 |

命令退出码为：成功或重复 `0`，等待 `0`，门禁阻断 `2`，忙碌、无效包或执行失败 `1`。平台不得只依据进程是否启动判断成功，应读取 `latest_trigger_summary.json` 的 `status`、`project_validation_accepted`、`project_simulation_passed` 和 `formal_experiment_status`。

## 5. 结论门禁

`completed` 只说明该数据版本的自动流程和质量检查通过。正式节能率、设备容量或运营调整建议仍需按项目约定完成业务负责人和数据负责人复核。`blocked`、`failed`、当前工程占位数据或未通过校准的数据均不得形成正式工程结论。
