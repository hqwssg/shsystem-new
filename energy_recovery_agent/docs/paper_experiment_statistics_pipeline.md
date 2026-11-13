# 论文实验自动化与统计链路

本文档说明如何把多个正式评价窗从冻结输入自动运行到论文统计表图。单评价窗算法执行仍由 `formal-experiment-suite` 负责；`paper-experiment-pipeline` 在其上增加研究清单、跨窗编排、完整性门禁和配对统计。正式主实验 F00-F05、F08 以及有数据时的 F10 校准证据均进入自动链路。

## 1. 链路边界

完整链路如下：

```text
预先确定评价窗和排除规则
    -> 冻结研究清单
    -> 每窗执行 F00/F01/F02/F03/F04/F08 与质量审计
    -> NSGA-II 多种子先在窗内取中位数
    -> 按评价窗与 B0 形成成对差值
    -> 描述统计、Bootstrap 区间、配对检验与 Holm 校正
    -> 论文 CSV、中文报告和 PNG 图
```

统计单位固定为独立评价窗。一个评价窗中的多个 NSGA-II 随机种子只衡量搜索算法的随机性，不能被当作多个独立线路样本。这条规则防止扩大样本量的伪重复。

## 2. 研究清单

复制并填写 `paper/实验设计/论文实验研究清单模板.json`。相对路径统一相对于项目根目录解析。核心字段如下：

| 字段 | 作用 |
| --- | --- |
| `study_id` | 本次研究的稳定编号 |
| `dataset_version` | 冻结正式数据版本 |
| `experiment_parameters` | 所有窗口共用的种子、搜索规模和调整边界 |
| `analysis.metrics` | 预先登记的统计指标 |
| `analysis.statistics_seed` | Bootstrap 和蒙特卡洛检验的复现种子 |
| `analysis.min_windows_for_inference` | 允许输出推断统计的最低有效窗口数 |
| `windows[].include` | 是否按预先规则纳入 |
| `windows[].exclusion_reason` | 排除时必须填写，不能看过优化结果后留空排除 |
| `windows[].data_dir/source_dir/timetable` | 执行模式使用的冻结输入 |
| `windows[].result_dir` | 仅汇总模式引用的既有单窗结果目录 |

每个纳入窗口必须存在且通过质量门禁的 B0 基线、B1 无储能、规则优化、清单声明的全部 NSGA-II 种子以及全部 F08 时间步长。缺少任一方案、种子或步长不一致、存在约束违反时，该窗口不会悄悄进入统计，而会写入失败与排除记录。

## 3. 执行命令

正式数据到位后，一条命令执行全部窗口和统计：

```powershell
python run_project.py paper-experiment-pipeline `
  --study-manifest paper/实验设计/正式研究清单.json `
  --output-root paper/experiments/formal/<研究编号>
```

如果各窗口已经由 `formal-experiment-suite` 计算完毕，可在清单中填写 `result_dir`，只重新汇总统计：

```powershell
python run_project.py paper-experiment-pipeline `
  --study-manifest paper/实验设计/正式研究清单.json `
  --output-root paper/experiments/formal/<统计批次> `
  --aggregate-only
```

统计目录非空时程序拒绝覆盖，防止不同研究批次混写。需要重算时应使用新的研究输出目录。

## 4. 自动统计口径

默认主指标为购电量、弃能、有效再生损失和回收率。改善量统一转换为“正值更优”：

- 购电、弃能、有效再生损失：`B0 - 对照方案`；
- 回收率：`对照方案 - B0`；
- NSGA-II：先对同一窗口的固定种子结果逐指标取中位数，再与该窗口 B0 配对。
- F05：在同一窗口内把规则法作为参照，直接计算 NSGA-II 相对规则法的改善。
- F08：1/5/10 秒使用相同运行图和正式设备参数，报告相对1秒结算误差与耗时。
- F10：汇总每个评价窗的校准证据路径、SHA-256、质量结论和验证指标；没有实测证据时不伪造结果。

每个策略和指标自动给出窗口数、均值、中位数、样本标准差、四分位数、范围、正改善窗口比例、配对 Cohen's dz、均值和中位数的百分位 Bootstrap 置信区间。双侧配对符号翻转检验用于检验平均配对差是否偏离零；主检验统一进行 Holm 多重比较校正。

当有效评价窗少于 `min_windows_for_inference` 时，仍生成数据和区间供核查，但 `inference_ready=false`、不输出可用于显著性声明的 p 值。统计显著不等于工程上值得采用，最终仍需结合门控阈值、绝对节能量和运行图调整代价解释。

## 5. 输出文件

| 文件 | 主要用途 |
| --- | --- |
| `STUDY_FREEZE_MANIFEST.json` | 研究清单、输入或既有结果、参数及程序版本的 SHA-256 证据 |
| `statistics/paper_analysis_rows.csv` | 每个评价窗、每个策略一行的分析就绪表 |
| `statistics/paper_paired_effects.csv` | 每窗相对 B0 的原始差值、方向统一改善量和改善率 |
| `statistics/paper_strategy_summary.csv` | B0、B1、规则法和窗内种子汇总后 NSGA-II 的跨窗绝对 KPI 描述统计 |
| `statistics/paper_statistical_summary.csv` | 描述统计、效应量、置信区间、原始及 Holm 校正 p 值 |
| `statistics/paper_seed_stability.csv` | 各窗 NSGA-II 跨种子的均值、中位数、标准差、CV 和范围 |
| `statistics/paper_exclusions.csv` | 预先排除、执行失败和质量门禁拒绝记录 |
| `statistics/paper_window_status.csv` | 所有预注册评价窗的纳入、完成、失败或排除状态 |
| `statistics/paper_timestep_sensitivity.csv` | F08 各评价窗在不同结算步长下的能量误差和耗时 |
| `statistics/paper_calibration_evidence.csv` | F10 各评价窗模型—电表校准证据和质量门禁 |
| `statistics/PAPER_STATISTICS_REPORT.md` | 可直接阅读和提取论文结果的中文报告 |
| `statistics/figures/paired_effects.png` | 各评价窗相对基线及 NSGA-II 相对规则法的成对改善散点图 |
| `statistics/figures/nsga2_seed_stability.png` | NSGA-II 跨种子购电量中位数及范围图 |
| `statistics/figures/timestep_sensitivity.png` | F08 各时间步长相对1秒结算的跨窗误差图 |
| `statistics/visualization_diagnostics.json` | 图形生成是否成功及失败原因 |

单窗 `formal_experiment_kpi.csv` 现在同时记录 `runtime_s`，可用于算法耗时统计。统一入口仍会另外生成运行清单，用于核对完整命令、代码版本、输入摘要和总耗时。

## 6. 结论边界

自动统计不改变数据可信等级。当前规划/占位参数只能验证链路、统计口径和相对机制；正式线路结论仍需正式数据准入。没有电表对齐时称为“基于正式输入的仿真比较”，使用规划储能参数时称为“规划参数情景”，样本窗不足时只报告案例或描述统计。

## 7. 当前异构实验总览

本工具处理格式统一的正式多评价窗统计。项目中已经存在的规模、精确求解、滚动恢复、校准、随机差分和异常输入实验使用不同结果结构，统一由下列命令汇总：

```powershell
python run_project.py aggregate-paper-experiments
```

该入口读取 `paper/实验设计/论文实验自动汇总清单.json`，更新 `paper/experiments/实验结果汇总.md`，并在 `paper/experiments/论文实验自动汇总/` 生成证据矩阵、关键指标长表、正式证据缺口、全部实验目录库存、源文件 SHA-256 和状态图。只有清单显式登记的当前证据进入论文结论，其他阶段目录统一列为历史或辅助证据，避免旧结果覆盖新结论。

回归验证命令：

```powershell
python tests/smoke/verify_paper_experiment_pipeline.py
python tests/smoke/verify_paper_experiment_aggregator.py
python tests/smoke/verify_formal_experiment_controller.py
```
