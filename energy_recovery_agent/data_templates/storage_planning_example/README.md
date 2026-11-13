# 储能选址定容阶段A合成输入

本目录是 `storage_planning_contract.py` 的可运行合成数据集，用于开发、合同校验和后续规划求解器测试，不代表朔黄铁路现场候选站址、设备价格或正式工程参数。

文件：

- `storage_candidate_sites.csv`：三个候选位置，其中两个可建设、一个用于验证不可建设候选语义；
- `storage_technologies.csv`：两组虚拟储能技术参数；
- `storage_site_technology_options.csv`：站点与技术的允许关系和局部上限；
- `storage_planning_scenarios.json`：正常、高运量、低运量三个概率场景；
- `storage_planning_policy.json`：预算、站点数、目标、风险和求解资源策略。

校验命令：

```powershell
python run_project.py validate-storage-planning `
  --input-dir data_templates/storage_planning_example `
  --power-arm-path data_templates/shuohuang_virtual/power_arm_intervals.csv
```

所有记录均标记为 `synthetic`，因此校验结果的 `recommendation_level` 必须为 `diagnostic_only`。复制本模板填报正式数据时，必须保留字段名和单位；在来源未经确认前不得把 `data_status` 改为 `official`。

本目录样例单独保存，不会自动发布到平台业务版本。浏览器维护使用 `../user_excel/储能规划.xlsx` 中文模板；算法原始文件仅用于隔离开发验证。
