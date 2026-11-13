# 项目文件整理与安全清理

当前正式数据尚未齐全时，可以先做文件治理、可复现性和测试维护，但不应因为“清理”而删除原始数据或改变算法口径。

## 已建立的只读盘点

运行：

```powershell
python tools/project_hygiene.py report
```

输出：

- `outputs/project_hygiene_report/PROJECT_HYGIENE_REPORT.md`：按用途分类、统计大小，并列出归档候选。
- `outputs/project_hygiene_report/manifest.json`：逐文件相对路径、分类、大小、修改时间和 SHA-256（用于归档前后核对）。
- `outputs/project_hygiene_report/ARCHIVE_PLAN.md` / `archive_plan.json`：仅计划、不执行的归档候选清单；`apply_required=true` 表示必须经过单独批准后才能移动。
- `outputs/project_hygiene_report/DATASET_COMPARISON.md` / `dataset_comparison.json`：数据快照逐文件 SHA-256 对比，区分完全一致、内容差异和部分缺失。

工具默认跳过 `.git`、虚拟环境、Python 缓存以及报告自身目录；**不会移动、删除或覆盖原有输入和结果**。

## 运行清单与可复现性

统一入口 `run_project.py` 会在命令开始前写入 `outputs/run_manifests/run_<时间>_<进程>_<随机串>.json`，结束时原位更新。当前清单 schema 为 `1.1`，包含：

- `code_version`：逐个 Python 源文件 SHA-256、代码快照 SHA-256，以及可用时的 Git 提交和工作区脏状态。
- `input_inventory`：输入根目录/文件、角色、大小、修改时间和 SHA-256；这是执行前快照。
- `arguments` 与 `arguments_sha256`：稳定排序后的参数快照及其摘要；`random_seeds` 只提取显式的 `seed`、`random_seed`、`numpy_seed`。
- `environment`：操作系统、CPU 架构、Python 实现/版本/解释器路径，以及关键依赖包版本（未安装的包记为 `null`）。
- `output_inventory`：执行后新建或更新的输出文件清单和 SHA-256 汇总。为避免重复扫描整个历史目录，目录型输出只纳入本次运行开始前后更新的文件，并排除 `outputs/archive/` 与 `outputs/run_manifests/`。
- `validation_status`、`data_status_after`、返回码和耗时：用于判断结果是否可接受及定位失败。

因此，两次运行是否可复现可以按 `code_version.code_snapshot_sha256`、`arguments_sha256`、输入文件 SHA-256、环境依赖版本和 `output_inventory.snapshot_sha256` 进行对比；不要仅比较输出目录名称或文件修改时间。

## 分类和处理边界

| 分类 | 典型路径 | 处理原则 |
| --- | --- | --- |
| 当前交付结果 | `outputs/SIMULATION_TEST_REPORT.md`、当前 dispatch/audit/optimization 目录 | 保留，作为当前复核口径 |
| 运行追溯证据 | `outputs/run_manifests/` | 保留；每个清单绑定一次命令、代码快照、输入哈希和最终状态，不得按旧输出批量清理 |
| 受保护输入/参考 | `data/source/`、`data/real_shuohuang/`、`data_templates/`、`tests/` | 不清理；正式数据接入前后都要可追溯 |
| 历史归档 | `outputs/archive/` | 保留目录结构，不作为当前结论 |
| 探针/旧输出候选 | `outputs/_*`、旧场景目录、历史恢复脚本 | 先核对引用，再移动到带日期的 `outputs/archive/YYYY-MM-project-hygiene/` |
| 日志/进程文件 | `*.log`、`*.pid`、空的 `*.err` | 确认没有审计要求后按保留期限清理；优先归档而非删除 |

## 当前发现的重点

历史材料主要集中在 `outputs/` 根目录的 `_*.py/.out/.err/.pid` 与大量旧场景目录，以及根目录和 `tools/` 下的恢复/临时脚本。数据目录中的 `real_shuohuang_backup_before_replace_*`、`real_shuohuang_rebuild_compare` 和 `real_partial` 是数据快照或兼容集，不能仅按“重复文件名”删除；如需瘦身，应先确认没有复现或审计用途，再整体归档并保留哈希清单。

当前全量报告发现内容完全相同的文件，但重复组主要横跨历史输出、测试夹具和数据快照；报告会按分类组合汇总，不能据此直接删除。尤其是 `data/`、`tests/`、`outputs/archive/` 和 `outputs/run_manifests/` 中的文件，必须保留其复现、回滚或审计语义。当前不建议执行“按哈希批量删除”。

2026-08-27 已执行一批低风险归档：12 个无活动引用、可由当前 smoke/实验流程重建的历史输出目录已移入 `outputs/archive/2026-08-project-hygiene/`，共 642 个文件。归档前后的 SHA-256 和文件大小已逐一核对；输入数据、模板、测试、运行清单和当前交付材料未移动。

## 归档后的最低验证

任何移动操作完成后，至少运行：

```powershell
python run_project.py smoke
python run_project.py validate-data
```

若默认输出、数据路径或文档引用发生变化，还应运行一次 `python run_project.py simulate` 并比较 `outputs/simulation_workflow_summary.json` 的输入路径和关键 KPI。正式数据到位后，先执行 `check-ingestion`，再替换当前数据集。

## 可恢复归档工具

`tools/archive_project_candidates.py` 接收显式路径，默认只生成计划；带 `--apply` 才会移动，并在每个文件移动后核对 SHA-256。归档目录中的 `ARCHIVE_MANIFEST.json` 记录原相对路径、大小和摘要；同一目录可分批归档，工具会累积既有清单，也可用 `--rebuild` 从归档内容重建清单。例如：

```powershell
python tools/archive_project_candidates.py --archive-dir outputs/archive/2026-08-project-hygiene-round3 tools/_tmp_example.py
python tools/archive_project_candidates.py --archive-dir outputs/archive/2026-08-project-hygiene-round3 --apply tools/_tmp_example.py
```

本轮已归档 49 个临时/恢复脚本，清单位于 `outputs/archive/2026-08-project-hygiene-round3/ARCHIVE_MANIFEST.json`；没有删除文件，恢复时按清单中的相对路径反向移动即可。
