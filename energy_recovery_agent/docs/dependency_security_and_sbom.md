# 依赖、安全与软件成分审计

## 1. 目的与范围

本审计覆盖正式依赖入口、当前运行环境中的传递依赖、许可证、原生二进制、公开已知漏洞、源码高风险调用、凭据模式、动态 SQL、子进程和 ZIP 解压。它用于回答“交付软件由什么组成、已知风险是什么、生产前还缺什么”，不替代渗透测试、甲方安全审批或目标环境验收。

审计策略位于 `security/audit_policy.json`。最新机器可读和人工可读证据输出到 `outputs/security_audit_20260913_final/`。

## 2. 当前结论

截至 2026-09-13，需区分旧正式环境与当前候选环境：

- 旧正式 v5 环境解析得到21个组件，Pillow 11.3.0命中18组独立已知漏洞；该结论继续作为旧环境风险记录；
- 当前候选增加`requirements-lock.txt`，锁定19个直接及传递组件及其SHA-256制品哈希；
- 源码安全门禁已通过，未发现嵌入式真实凭据、动态代码执行、`shell=True` 或未经安全封装的 ZIP 批量解压；具体扫描数量以最新机器证据为准；
- 4 处动态 SQL 使用源码固定表名或角色名集合，运行值使用参数绑定，已作为人工复核例外登记；
- 5 组恶意 ZIP 自测通过，路径穿越、符号链接、非法限制和解压体积超限均被拒绝；
- 当前Python 3.12.13候选环境中Pillow为12.3.0；OSV对19个组件查询19/19成功，已知漏洞0、未知许可证0、阻断项0；
- `requirements-lock.txt`已由审计程序实际核验：19个组件全部覆盖、锁定版本与Python 3.12.13验证环境一致、每项均含SHA-256制品哈希；
- 当前候选SBOM通过CycloneDX 1.6官方schema；最新证据位于`outputs/security_audit_20260913_final/`。

依赖安全门禁当前无阻断项；生产发布仍为`blocked`，原因是本轮审计工具变更尚未冻结和完成对应版本验收，且目标数据库与目标部署环境尚未验收。

## 3. 已完成修复

原先多个交付包验证器直接使用 `zipfile.extractall()`。现在统一通过 `tools/safe_zip.py`：

- 解压前验证所有成员；
- 拒绝绝对路径、盘符、`..` 路径穿越和 Unix 符号链接；
- 默认最多 5000 个成员、解压后总量不超过 1 GiB；
- 算法、数据库、生产保障和项目文档 ZIP 验证器统一使用该入口；
- 数据库独立依赖由范围声明改为 `psycopg[binary]==3.2.13`；
- 软件成分审计不再无条件报告“制品哈希未锁”，而是检查锁文件存在性、依赖闭包覆盖、精确版本一致性和逐组件SHA-256哈希；
- 发布就绪与最终审计汇总已将哈希锁纳入正式门禁，并以完整源码基线判断是否允许生产发布。

## 4. 生产前开放项

| 优先级 | 开放项 | 完成标准 |
| --- | --- | --- |
| 已完成 | Python 3.11/3.12隔离重建、Pillow升级和依赖哈希锁 | 干净环境矩阵、OSV及SBOM证据已形成 |
| 阻断 | 当前变更尚未形成新正式版本 | 当前候选包95项默认短测已通过；本轮新增安全门禁后的当前源码默认短测96/96通过，仍需在下一次冻结时完成完整发布验收并原子更新正式版本指针 |
| 阻断 | 目标环境尚未验收 | 在目标PostgreSQL、平台主机及正式部署网络完成安装和五类任务闭环 |
| 中 | 项目没有 LICENSE/COPYING/NOTICE | 由项目权利人确定软件权属、使用范围和对外交付许可，不得由开发人员擅自选择 |
| 复核 | psycopg 使用 LGPL-3.0-only | 交付前由法务或软件合规负责人确认告知和部署方式 |

## 5. 审计命令与输出

离线源码门禁可进入日常 CI：

```powershell
python tools/security_source_checks.py --output-dir outputs/security_audit_20260913_final/source_checks_final
```

联网软件成分审计：

```powershell
python tools/software_composition_audit.py --output-dir outputs/security_audit_20260913_final/composition
pwsh -File tools/validate_cyclonedx_sbom.ps1 -SbomPath outputs/security_audit_20260913_final/composition/sbom.cyclonedx.json -OutputPath outputs/security_audit_20260913_final/composition/sbom_schema_validation.json
python tools/finalize_security_audit.py --audit-root outputs/security_audit_20260913_final
```

主要输出：

- `software_composition_audit.json`：完整组件、依赖关系、许可证、二进制哈希、依赖制品哈希锁核验和 OSV 原始证据；
- `sbom.cyclonedx.json`：CycloneDX 1.6 软件物料清单；
- `third_party_components.csv`：适合筛选和移交的第三方组件表；
- `THIRD_PARTY_NOTICES.md`：第三方许可证告知；
- `SOFTWARE_COMPOSITION_AUDIT_REPORT.md`：审计结论和开放项；
- `security_source_checks.json`：源码门禁和恶意 ZIP 自测结果。
- `sbom_schema_validation.json`：基于官方CycloneDX 1.6 JSON Schema的验证结果及schema哈希。
- `SECURITY_AUDIT_SUMMARY.md`和`security_audit_summary.json`：区分“审计证据完整”与“允许生产发布”的最终总览。

联网审计必须在发布前 7 天内重新执行。OSV 零命中只代表查询时点的公开数据库结果；查询失败、未知许可证或精确版本不一致均应阻断发布。

## 6. 证据限制

当前证据来自项目自有静态门禁、Python安装元数据、文件SHA-256、官方OSV API和CycloneDX官方schema。尚未使用`pip-audit`、Bandit等第二套工具交叉核验，也未替代甲方安全审批或渗透测试。
