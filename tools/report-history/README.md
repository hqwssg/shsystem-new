# 业务历史数据增量包

本目录用于把经过确认的本地业务历史数据增量导入其他同版本环境，同时保留目标环境已有数据。

包含范围：

- 历史采集记录及审核流水；
- 核算任务、任务节点、采集节点核算明细、节点汇总和数据版本；
- 年度及其他历史周期的核算结果；
- 报告任务正文 JSON、报告业务明细、生成快照和已有报告附件。

不包含企业默认档案和默认图片；这些内容仍由 `tools/report-defaults/init_report_defaults.sh` 初始化。

## 安全规则

导入器只执行缺失记录插入，不更新、不删除目标库中的任何原有记录。导入前会完成完整备份，并在一个事务中执行。关键主键指向不同业务对象、业务唯一键对应不同主键、父记录缺失或表结构不兼容时，整个事务会回滚。

当前本地快照没有已生成的历史 DOCX/PDF 附件，所以包中报告历史正文来自 `report_task` 的正文 JSON 和 `report_generation_job.input_snapshot_json`，不会伪造不存在的附件。

## 重新生成数据包

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File tools/report-history/export-history.ps1
```

脚本从本地 `carbon_emissions` 读取数据，密码只用于当前进程，不写入生成文件。

## 服务器导入

把本目录上传到服务器后执行：

```bash
bash init_business_history.sh \
  --container ruoyi-db \
  --database carbon_emissions \
  --user root \
  --backup-dir /opt/ruoyi-backups/business-history-$(date +%Y%m%d-%H%M%S)
```

成功标志：

```text
BUSINESS_HISTORY_INIT_OK
```

