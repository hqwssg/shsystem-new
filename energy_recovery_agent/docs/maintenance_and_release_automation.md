# 维护性与发布自动化

## 1. 自动化边界

维护流程负责持续发现源码、文档、交付包和环境漂移；发布流程负责候选预检、冻结、构建、核验和正式验收。两者不会替代正式数据验收、目标环境验收或甲方安全审批，也不会自动删除历史证据。

旧正式环境的Python 3.9和Pillow风险已经由当前候选的Python 3.11/3.12干净环境及哈希锁方案处置。当前生产发布仍因候选未冻结、独立长测和目标环境验收未完成而阻断。

## 2. 日常维护

```powershell
python tools/run_maintenance.py
python tools/run_maintenance.py --full-smoke
```

默认流程执行：

1. 本地CI，包括编译、接口、文档、算法检查和源码安全门禁；
2. 非破坏性项目卫生报告；
3. 发布状态、审计证据和运行时就绪检查；
4. 当前算法包、文档包、数据库包和生产保障包完整性核验。

本地CI当前为20项，包含`requirements-lock.txt`结构、直接依赖覆盖和逐项SHA-256哈希检查。

输出位于 `outputs/maintenance_current/`。`maintenance_passed=true` 表示维护机制和当前交付物没有结构性故障；`production_release_ready=false` 表示存在生产阻断，两者不得混为一谈。维护任务通过 `outputs/.maintenance.lock` 防止并发运行。

## 3. 发布就绪检查

```powershell
python tools/release_readiness.py --stage maintenance
python tools/release_readiness.py --stage candidate
python tools/release_readiness.py --stage acceptance
```

- `maintenance`：允许存在未冻结开发变化，将其作为状态披露；
- `candidate`：要求版本号已高于上一基线、存在待冻结变化、目标包路径未占用，并且安全门禁全部通过；
- `acceptance`：要求源码与冻结基线完全一致、包已存在、安全证据有效。

版本采用 `YYYY.MM.DD.N`，包名必须对应 `algorithm_release_YYYYMMDD_vN`。版本号、包名、文档登记、Python支持状态、OSV查询完整性与时效、已知漏洞、许可证和CycloneDX schema均自动检查。

## 4. 一键发布编排

```powershell
python tools/automate_release.py check
python tools/automate_release.py freeze-build --built-at-utc 2026-09-11T08:00:00Z
python tools/automate_release.py accept
python tools/automate_release.py all --built-at-utc 2026-09-11T08:00:00Z
```

使用前先把 `release/package_spec.json` 和当前文档登记更新为明确的新版本。`check`不修改基线。`freeze-build`只有在候选门禁通过后才会冻结和构建；任一步失败会恢复原基线并清理本次创建的包。`accept`执行完整发布验收。`all`依次执行全部阶段。

`--skip-long`只能用于诊断，最终结论必定不是正式通过。发布总控使用 `outputs/.release_pipeline.lock`，算法包构建器还使用输出目录内的独立构建锁。

冻结基线只表示候选代码快照，不等于正式验收通过。`release/accepted_release.json`是正式版本指针，同时绑定完整验收摘要和算法ZIP的SHA-256；只有`accept`或`all`完成全部门禁后才会原子更新。日常维护始终核验该指针指向的正式包，不会把失败候选当成当前正式版本。

## 5. 原子与可复现构建

算法包先在交付目录内的临时 staging 目录构建，全部文件、清单、校验和和ZIP完成后才移动到正式路径。构建异常会清理 staging；目标已存在时拒绝覆盖。

传入相同基线、包名和 `--built-at-utc`，或者设置相同 `SOURCE_DATE_EPOCH`，ZIP成员顺序、时间和权限固定，生成文件应具有相同SHA-256。未指定固定时间时仍记录真实UTC构建时间，因此不同运行的ZIP哈希可以不同。

## 6. 正式安全门禁

`tools/run_release_acceptance.py`现在固定包含 `release_security`：

1. 重新联网查询所有依赖的OSV记录；
2. 重新生成CycloneDX 1.6 SBOM；
3. 使用官方schema验证SBOM；
4. 检查Python支持周期、漏洞、许可证、证据时效和源码安全；
5. 任一阻断项失败时停止后续高成本验收。

`tools/release_security_gate.py --reuse-evidence`仅供诊断，使用后强制判定不允许正式发布。

## 7. 恢复和人工处理

锁文件不会因无法确认所有者状态而自动删除，避免并发任务被误判为过期。若任务异常终止，应先确认对应PID和主机上没有维护或发布进程，再由维护人员移走锁文件并保存现场信息。

历史包归档仍需明确选择路径并采用可恢复移动。自动化不运行通配删除，不覆盖同名包，不修改正式数据目录。

## 8. 干净环境与可移植性

```powershell
python tools/clean_environment_portability.py
```

该工具从正式ZIP和当前候选白名单分别建立载荷，在全新Python 3.11/3.12虚拟环境中安装依赖，执行编译、关键smoke、中文空格路径下的中立目录调度和源文件不变检查；Python 3.12候选额外执行完整短测。`--allow-download-cache`只复用下载文件，不复用虚拟环境或系统site-packages。Linux、真实PostgreSQL和正式数据需另行验收。
