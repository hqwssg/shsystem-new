# 正式数据就绪流水线

`tools/official_data_readiness_pipeline.py` 用于正式数据到位后的第一道自动化门禁。它是只读的：不会覆盖 `data/real_shuohuang`，也不会修改 `data/source`。

## 流程

1. 对候选 `--data-dir` 生成逐文件 SHA-256 清单。
2. 调用 `formal_data_acceptance.run_acceptance`，同时检查字段质量、来源状态和接入一致性。
3. 验收失败立即阻断；因此当前包含虚拟/占位数据的目录会正常返回失败，不能被误发布。
4. 只有显式提供 `--run-simulation` 且验收通过时，才在输出目录下的隔离 `simulation/` 运行仿真。
5. 对隔离结果执行 `result_quality_audit`；可用 `--baseline-output` 对比基线 JSON 数值 KPI，差异只记录、不自动判定业务好坏。

## 示例

```powershell
python run_project.py official-data-readiness `
  --data-dir data/official_inbox/converted_runtime `
  --source-dir data/official_inbox/source `
  --timetable data/official_inbox/timetable.xlsx `
  --output-dir outputs/official_readiness_2026_08_29
```

底层脚本 `tools/official_data_readiness_pipeline.py` 仍可直接调用，参数相同。

需要运行隔离仿真时追加 `--run-simulation`；需要比较已有结果时追加 `--baseline-output outputs/synthetic_regression_baseline`。输出包括 `candidate_manifest.json`、`readiness_summary.json`，以及仿真和质量审计报告（若执行）。

该工具不提供隐式 `--apply` 操作。正式发布仍须人工审核清单、双签和明确的目标目录，避免候选数据误覆盖当前运行输入。

若需要在数据到件后自动冻结快照、运行完整工程仿真并继续执行正式对比总控，使用[正式数据到件自动触发流程](official_data_auto_trigger.md)。
