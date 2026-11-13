# 生产运行保障工具包说明

## 1. 交付目的

本工具包把生产运行预案、监控阈值、统一预检、运行快照、备份恢复演练和本地证据集中交付。它可以在没有甲方配合时完成部署前准备和本地验证，但清单始终保持`production_accepted=false`；目标环境项目完成前不能据此宣布上线。

工具包是匹配版本完整算法包上的运维覆盖包，不是脱离算法源码独立运行的程序。使用前应保持工具包中的相对路径覆盖到对应算法包根目录，或直接在同版本完整项目中执行。

## 2. 核心入口

| 入口 | 作用 |
| --- | --- |
| `tools/production_assurance_preflight.py` | 校验工具、依赖、worker策略、凭据模板、发布基线、磁盘和算法运行准备度；可选连接数据库 |
| `tools/production_operations_snapshot.py` | 读取只读数据库指标和主机磁盘，按冻结策略生成告警 |
| `tools/production_database_backup_restore.py` | 创建逻辑备份，在全新`_restore_test`库恢复并核验后清理 |
| `tools/run_local_production_assurance.py` | 串联专项回归、预检、运行快照和恢复演练 |
| `tools/verify_production_assurance_package.py` | 核验目录包、ZIP、证据状态和逐文件SHA-256 |

## 3. 完整本地演练

本地PostgreSQL必须已经完成项目迁移。演练连接可以使用本地测试账号；正式环境必须使用分离账号和TLS。

```powershell
python tools/run_local_production_assurance.py `
  --acceptance-database-url $env:SIMULATION_ACCEPTANCE_DATABASE_URL `
  --readonly-database-url $env:SIMULATION_READONLY_DATABASE_URL `
  --backup-source-url $env:SIMULATION_BACKUP_SOURCE_DATABASE_URL `
  --admin-url $env:POSTGRES_ADMIN_URL `
  --pg-bin '<PostgreSQL bin目录>' `
  --output-root outputs/production_assurance_local
```

本地完成条件：总控`local_ready=true`、运行快照无Critical、恢复演练`accepted=true`、隔离恢复库已清理。`production_accepted`仍必须为false。

## 4. 包内容边界

工具包包含源工具、非敏感策略模板、中文预案、本地演练摘要、发布验收摘要和长测门禁摘要。数据库备份本体不进入ZIP，只在恢复报告中记录文件位置、大小和SHA-256。连接串、密码、私钥和甲方通知地址均不包含。

构建命令需要显式指定本地证据和对应算法版本的发布验收目录：

```powershell
python tools/build_production_assurance_package.py `
  --local-evidence <本地演练证据目录> `
  --release-acceptance <当前发布验收目录> `
  --package-id <新的保障包ID>
```

构建器拒绝覆盖同名目录或ZIP。核验命令：

```powershell
python tools/verify_production_assurance_package.py `
  --package-dir <保障包目录> `
  --zip <保障包ZIP>
```

## 5. 甲方接手后的最短路径

1. 阅读`production_operations_runbook.md`和验收清单。
2. 在目标环境注入正式账号和TLS连接，不修改工具包保存凭据。
3. 运行生产预检、数据库健康检查和账号权限探针。
4. 接入运行快照JSON到监控平台并实测告警通知。
5. 在正式备份介质完成恢复演练并批准RPO/RTO。
6. 重跑目标负载、五类任务和故障演练。
7. 完成外部验收清单并由责任方签字。
