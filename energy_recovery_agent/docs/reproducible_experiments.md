# 端到端拟真测试复现清单

本文档说明当前项目如何复现拟真测试，以及如何解释输出结果。所有命令均从项目根目录运行。

## 0. 环境准备

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\tools\setup_utf8_env.ps1
```

## 1. 一键拟真测试

```powershell
python run_project.py simulate
```

该命令会依次执行（默认不覆盖现有数据；只有增加 `--rebuild-data` 才会重新生成 `data/real_shuohuang/`）：

1. 校验选定数据目录；如指定 `--rebuild-data`，先从审核源表重建数据目录。
2. 校验真实数据和预设参数。
3. 抽取智能电表代表样本，并与线路运行弧对齐。
4. 审查预设运行图中的再生能量浪费风险。
5. 生成 NSGA-II 运行图优化候选和帕累托方案。
6. 运行重空列协同调度拟真。
7. 写出总报告 `outputs/SIMULATION_TEST_REPORT.md`。

## 2. 多 Case 与敏感性测试

```powershell
python run_project.py experiment-suite
```

该命令会运行多组预设运行图 case 和关键参数敏感性测试，并生成中文解读报告。

主要输出：

```text
outputs/simulation_experiment_suite/SIMULATION_EXPERIMENT_INTERPRETATION_REPORT.md
outputs/simulation_experiment_suite/simulation_experiment_summary.csv
outputs/simulation_experiment_suite/simulation_experiment_summary.json
outputs/simulation_experiment_suite/figures/
outputs/simulation_experiment_suite/cases/
```

最近一次实验套件结果：

| 项目 | 结果 |
| --- | ---: |
| 实验总数 | 8 |
| 优化方案可行实验数 | 6 |
| 当前推荐 3重3空 case | 可行，资源冲突 0 |
| 冲突相位 3重3空 case | 不可行，资源冲突 2 |
| 运行图优化 Pareto 候选 | 30 |

## 3. 单独复现命令

数据校验：

```powershell
python run_project.py validate-data
```

电表代表样本：

```powershell
python run_project.py meter-samples
```

运行图审查：

```powershell
python run_project.py audit-timetable
```

运行图优化：

```powershell
python run_project.py optimize-timetable
```

调度拟真：

```powershell
python run_project.py dispatch-case
```

快速验证：

```powershell
python run_project.py smoke
```

## 4. 主要输出文件

| 输出 | 说明 |
| --- | --- |
| `outputs/SIMULATION_TEST_REPORT.md` | 一键拟真测试总报告。 |
| `outputs/simulation_workflow_summary.json` | 端到端流程机器可读汇总。 |
| `outputs/timetable_optimizer_nsga2/pareto_candidates.csv` | 运行图优化帕累托候选。 |
| `outputs/dispatch_storage_no_direct_phase2600/DISPATCH_CASE_REPORT.md` | 当前推荐调度拟真报告。 |
| `outputs/dispatch_storage_no_direct_phase2600/kpi_summary.csv` | 当前推荐调度 KPI 汇总。 |
| `outputs/simulation_experiment_suite/SIMULATION_EXPERIMENT_INTERPRETATION_REPORT.md` | 多 case 与敏感性测试解读报告。 |

每次上述统一入口命令还会在 `outputs/run_manifests/` 自动生成一个 schema-`1.1` 运行清单。清单记录本次命令、解析参数及稳定摘要、显式随机种子、代码/输入/本次输出文件 SHA-256、平台与关键依赖版本、数据状态、可发现的校验摘要、返回码和耗时。它在执行前写入 `running`，结束后写入 `success`/`failed`，用于把报告与具体数据版本绑定；它不是需要人工填写的输入。

复现或比较结果时，先按时间/PID/随机 ID 找到对应 `run_*.json`，确认 `status=success` 和 `return_code=0`，然后比较 `code_version.code_snapshot_sha256` 与 `input_inventory.files[].sha256`。若输入或代码哈希不同，不应把 KPI 差异直接归因于算法改动。

## 5. 结果解释边界

当前结果可以说明：

- 真实主线数据已经接入算法流程；
- 供电臂、坡度、平曲线、编组、预设运行图、电表代表样本可以形成端到端拟真链路；
- 运行图评估和优化器可以输出一组可选帕累托方案；
- 调度拟真可以输出可行的重空列协同方案和能量结算结果；
- 参数敏感性测试可以展示预设值变化对结果趋势的影响。

当前结果不能直接作为：

- 最终工程节能量结论；
- 储能容量或投资收益结论；
- 正式生产运行图优化结论；
- 精确牵引计算结果。

原因是正式运行图、真实储能设备参数、机车牵引/制动曲线、车辆阻力参数仍采用预设或占位值。

## 6. 正式论文多窗口实验

正式数据到位后，不再逐窗口人工复制 KPI。先填写 `paper/实验设计/论文实验研究清单模板.json`，再运行：

```powershell
python run_project.py paper-experiment-pipeline `
  --study-manifest paper/实验设计/正式研究清单.json `
  --output-root paper/experiments/formal/<研究编号>
```

该入口依次调用每个评价窗的正式实验总控，并自动生成分析就绪表、成对差值、NSGA-II 种子稳定性、Bootstrap 置信区间、配对检验、Holm 校正和论文图。详细口径见 [论文实验自动化与统计链路](paper_experiment_statistics_pipeline.md)。
