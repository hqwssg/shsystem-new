# 正式版本基线、完整算法交付包与统一发布验收

## 1. 当前正式软件版本

- 上一正式算法发布版本：`2026.09.11.5`
- 当前候选算法版本：`2026.09.13.2`
- 平台接口冻结版本：`1.3.1`
- 正式v5 Python范围：`>=3.9,<3.13`；当前候选范围：`>=3.11,<3.13`
- 当前数据状态：`planning_placeholder`

候选版本由`release/package_spec.json`定义范围，由`release/release_baseline.json`冻结逐文件大小和SHA-256。任何白名单文件新增、删除或变化都会导致基线核验失败，必须先完成修改和测试，再显式生成下一版本基线，不能在构建交付包时自动接受变化。`2026.09.13.2`用于收口Python运行环境、依赖哈希锁审计、发布门禁修正和文档登记载荷完整性；完成冻结、构建与全范围验证前不得视为正式发布。

`release/release_baseline.json`只证明候选源码被冻结；`release/accepted_release.json`才表示某个版本完成全范围验收。后者绑定验收摘要和算法ZIP的SHA-256，只能由发布自动化在完整验收成功后推进。

`2026.09.11.5`在已经通过完整门禁的`2026.09.11.4`基础上完成文档状态收敛：新增唯一当前状态入口、逐文件状态登记、文档包构建与自动核验，修正旧测试数量和版本引用，并移除生产保障说明中的固定旧版本目录。算法计算、业务任务类型、字段、单位和状态语义未改变，平台接口冻结版本仍为`1.3.1`。

上述Python范围是v5冻结时的代码兼容声明，不等于当前生产安全支持范围。安全策略要求生产最低Python 3.11、优先3.12；当前Python 3.9与Pillow漏洞未处置，因此v5之后的安全加固工作区尚未冻结为新正式发布。

## 2. 交付包范围

完整算法包包含算法源码、统一入口、数据库接入层、运行时规划数据、输入模板、当前短测与长测、工具脚本、原型接口材料和当前项目文档。

以下内容有意排除：原始电表和甲方来源文件、正式数据收件箱、运行输出、论文目录、历史测试、旧交付包及甲方参考原件。排除原始来源数据不会影响当前默认算法运行；正式数据应通过版本化数据库快照或独立交付目录接入。

直接运行依赖固定在`requirements.txt`，当前候选同时提供带传递依赖和制品SHA-256的`requirements-lock.txt`；数据库单独部署时仍可使用`requirements-database.txt`。

## 3. 构建与核验

仅在确定要发布新版本时冻结基线：

```powershell
python tools/freeze_release_baseline.py
```

构建当前交付包：

```powershell
python tools/build_algorithm_delivery_package.py
```

同时核验工作区、目录包和ZIP：

```powershell
python tools/verify_algorithm_delivery_package.py `
  --source `
  --package-dir deliverables/algorithm_release_20260913_v2 `
  --zip deliverables/algorithm_release_20260913_v2.zip
```

构建器不会覆盖同名目录或ZIP。重发必须使用新版本和新包名，旧包按项目归档规则保留。

## 4. 统一发布验收

```powershell
python tools/run_release_acceptance.py
```

正式门禁固定执行：

1. 工作区基线、目录包和ZIP完整性；
2. 临时解压后的精确依赖与包内代表性运行检查；
3. 联网刷新OSV和SBOM、官方CycloneDX schema、Python支持周期及源码安全门禁；
4. 平台接口冻结合同；
5. 本地CI式检查；
6. 全部默认短耗时smoke；
7. 全部独立长耗时回归及冻结性能门禁，包括重复测量中位耗时和进程树峰值RSS。

候选冻结前还应运行`tools/clean_environment_portability.py`，至少覆盖Python 3.11和3.12、中文空格路径、中立工作目录启动及锁定依赖安装。当前Windows证据不等同于Linux或目标平台运行验收。

任一门禁失败即停止后续高成本检查，并保留已执行项目的标准输出和错误输出。只有`complete_scope=true`且`accepted=true`才能称为正式软件版本通过发布验收。`--skip-long`只能用于开发诊断，结果必定不能批准发布。

长测门禁配置位于`release/long_test_performance_gate.json`，当前是规划/合成数据的软件回归线，不是生产SLA。正式数据和目标硬件到位后必须重新标定，具体见`docs/long_test_performance_gate.md`。

2026-09-11当前候选已在Python 3.12.13干净环境完成独立长测：7/7项、9/9次执行通过，`complete_scope=true`、`accepted=true`，测试前后候选载荷SHA-256一致。该证据位于`outputs/long_test_performance_gate_py312_20260911/`；它消除了当前候选的长测开放项，但不等于候选已经冻结或完成统一发布验收。

默认报告目录为`outputs/release_acceptance/`，人读和机器读入口分别是`RELEASE_ACCEPTANCE_REPORT.md`与`release_acceptance_summary.json`。

推荐使用自动编排入口：

```powershell
python tools/run_maintenance.py
python tools/automate_release.py check --audit-root outputs/security_audit_20260913_v1
python tools/automate_release.py all --audit-root outputs/security_audit_20260913_v1 --built-at-utc <ISO-8601 UTC时间>
```

候选检查不通过时不会冻结基线或创建交付包。构建过程使用临时目录、进程锁和失败回滚；固定构建时间后，相同基线可以生成字节一致的ZIP。详细规则见`maintenance_and_release_automation.md`。
