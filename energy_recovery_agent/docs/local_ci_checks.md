# 本地持续集成式检查

## 长耗时调度回归

长耗时测试不再依赖一次串行 smoke 才能观察结果，可独立运行：

```powershell
python tools/run_long_dispatch_tests.py
python tools/run_long_dispatch_tests.py --test heavy_empty_network
python tools/run_long_dispatch_tests.py --test rolling_optimizer
python tools/run_long_dispatch_tests.py --test historical_disturbance_replay
```

每个测试有独立超时、标准输出和错误输出，汇总写入 `outputs/long_dispatch_tests/`。完整运行还执行冻结的性能门禁：两个主要热点重复2轮，采集整个进程树峰值RSS，并检查中位耗时和内存回归线。单项命令仅用于诊断，不代表完整门禁通过；详细口径见`docs/long_test_performance_gate.md`。
历史扰动回放端到端测试包含四轮完整滚动求解，默认独立超时为1200秒；超时只表示未在预算内完成，不能解释为算法不可行。

`python run_project.py smoke` 默认排除其中位于 `tests/smoke/` 的5个长耗时脚本，当前运行96个短测试。需要从统一入口执行全部101个脚本时使用 `python run_project.py smoke --include-long`；`--only <脚本stem>` 可直接点名长耗时脚本。

如果并行启动多个运行器，必须为每个进程指定不同的 `--output-dir`，避免汇总文件互相覆盖。

在没有远程 CI 服务的情况下，使用统一脚本执行本地质量门禁：

```powershell
python tools/run_ci_checks.py --output-dir outputs/ci_checks
```

本地CI还会执行 `tools/verify_documentation_status.py`，检查全部受管文档均被唯一分类、当前权威入口与发布版本一致、权威文档链接有效且不含已禁止的旧状态口径。
它还执行离线源码安全门禁，检查高置信度凭据、高风险调用、`shell=True`、动态代码执行、不安全ZIP解压、直接依赖精确锁定和安全ZIP自测。OSV联网查询不放入日常CI，必须在发布前单独生成有时间戳的软件成分审计证据。

默认检查：

- Python编译、原型/后端契约和原型资源同步；
- 性能容量、合成场景、合成回归、静态异常和极端输入；
- 平台数据库接口冻结及文档状态；
- 算法一致性、稳健性、属性、扩展和综合验证；
- 运行准备度及论文异构实验汇总边界；
- 源码安全、安全ZIP自测及维护/发布自动化性质。

本工具是日常开发门禁，不单独代表正式发布。正式发布使用`python tools/run_release_acceptance.py`，它还会核验正式源码基线、完整算法目录包和ZIP，并追加全部短耗时与长耗时回归。完整规则见`docs/release_baseline_and_delivery.md`。

Python 编译只扫描项目自身源码、工具和测试，明确排除 `.venv/`、`outputs/`、`data/` 等目录，避免第三方包版本高于当前解释器时产生误报。

需要完整回归时增加 `--full-smoke`。报告输出到 `CI_CHECKS.md` 和 `ci_summary.json`，每项检查的 stdout/stderr 单独保存。该脚本只执行验证，不修改算法逻辑；正式数据接入前不得用它替代正式数据验收清单。
