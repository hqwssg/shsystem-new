# 正式实验自动化总控

`formal-experiment-suite` 用于正式数据通过严格验收后的单评价窗口对比实验。它不修改 `data/real_shuohuang/`、`data/source/` 或甲方原始交付目录。

## 1. 自动执行内容

一次运行按固定顺序生成以下结果：

| 编号 | 自动步骤 | 输出目录 |
| --- | --- | --- |
| F00 | 正式数据只读验收、输入文件清单和验收报告 | `F00_readiness/` |
| F01 | 现行正式运行图基线能量审查 | `F01_B0_baseline/` |
| F02 | 无储能消融：复制正式运行时数据后关闭储能能力 | `F02_B1_no_storage/`、`derived_configs/` |
| F03 | 规则候选运行图优化 | `F03_R1_rule/` |
| F04 | 每个固定种子的 NSGA-II 运行图优化 | `F04_NSGA_seed_<seed>/` |
| F08 | 1/5/10 秒结算时间步长敏感性和逐方案质量审计 | `F08_timestep_<step>s/` |
| F99 | 每个方案输出质量审计 | 各方案目录的 `F99_quality_audit/` |
| 汇总 | 统一 KPI 表、机器可读总览和中文报告 | 输出根目录 |

F02 只生成派生实验副本。它会将副本中的储能容量、充放电功率设为 0，并将所有供电臂标记为不可用储能；原始正式数据不会被改写。

## 2. 使用前提

1. 正式运行时数据、来源目录和运行图已冻结，并具有版本、字段映射和 SHA-256 清单；
2. 数据状态为 `official` 或 `derived_from_official`，无未声明的规划/虚拟参数；
3. 运行图已转换为内部规范格式；
4. 已由运营方确认允许的最大时刻偏移、最小调整步长和最大停站延长时间；
5. 每个评价窗口使用独立、原本为空的输出目录。

若 F00 验收未通过，总控将返回 `blocked`，只保留验收报告，不会执行 F01 至 F04。这是设计要求，不是算法故障。

## 3. 推荐命令

```powershell
python run_project.py formal-experiment-suite `
  --data-dir data/official_inbox/converted_runtime `
  --source-dir data/official_inbox/source `
  --timetable data/official_inbox/timetable_2026-09-01.xlsx `
  --output-root paper/experiments/formal/v2026-09-01/window_2026-09-01 `
  --window-id 2026-09-01 `
  --max-shift-min 10 `
  --step-min 5 `
  --max-dwell-extension-min 5 `
  --max-candidates 50 `
  --population-size 20 `
  --generations 20 `
  --seeds 11 23 37 53 71
```

默认启用严格图表生成。只有排查绘图环境问题时才使用 `--no-strict-visualizations`；正式论文实验不应关闭该检查。

也可直接运行脚本：

```powershell
python tools/formal_experiment_controller.py --help
```

## 4. 主要输出与判读

| 文件 | 用途 |
| --- | --- |
| `formal_experiment_summary.json` | 总控状态、输入、参数、验收结论、每个方案的详细结果 |
| `formal_experiment_kpi.csv` | 跨方案 KPI 表，含相对 B0 的购电、弃能和有效再生损失变化 |
| `formal_timestep_sensitivity.csv` | F08 各时间步长的能量指标、相对1秒误差、质量状态和耗时 |
| `FORMAL_EXPERIMENT_REPORT.md` | 供人工阅读的中文汇总报告 |
| `run_manifests/` | 统一入口生成的运行清单、代码快照和参数追溯信息 |
| `derived_configs/F02_no_storage_runtime/DERIVED_NO_STORAGE_MANIFEST.json` | 无储能消融的全部派生修改记录 |

只有 `status=completed`、`quality_accepted=True` 且候选满足硬约束的方案可以进入论文主结果表。若优化方案的门控结论为 `keep_baseline`，应如实报告“该评价窗口内没有足以替换基线的净收益”。

`formal_experiment_kpi.csv` 还记录每个方案的 `runtime_s`。该值是本次进程中的墙钟耗时；正式论文比较应固定硬件、后台负载和软件环境，并结合统一运行清单复核。

多个评价窗不要人工拼表。应使用 [论文实验自动化与统计链路](paper_experiment_statistics_pipeline.md) 的研究清单入口，由程序先在窗内汇总 NSGA-II 种子，再进行跨窗配对统计。

## 5. 不包含的工作

总控不替代电表/功率数据校准。若已获得可匹配电表样本，应先运行 `calibrate-energy` 并把校准版本记录在正式数据包中；使用 `--calibration-summary <pipeline_summary.json> --require-calibration` 可以要求校准质量通过后才启动正式对比实验。详细门禁和误差指标见[模型结果—电表数据校准与误差分析链路](model_meter_calibration_and_error_analysis.md)。没有实测对齐时，实验结论应称为“基于正式输入参数的仿真比较”，不能称为现场节能量验证。

储能额定值误差区间、运行图调整幅度和直供规则边界情景不在默认单窗总控内；它们属于推荐或可选补充实验，应按 [正式数据到位后对比实验方案](../paper/实验设计/正式数据到位后对比实验方案.md) 中的 F06、F07、F09 单独执行。F08 的 1/5/10 秒时间步长和多随机种子稳定性已经自动执行；F10 校准证据会写入单窗汇总，并由跨窗统计链路统一汇总。
