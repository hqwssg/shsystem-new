# 长耗时测试性能门禁

## 1. 目的与边界

长测门禁用于发现算法仍能返回正确结果、但执行时间或内存已经明显退化的版本。它覆盖7项调度与运行图长测，同时检查功能返回码、逐轮超时、重复测量中位耗时和整个进程树的峰值常驻内存（RSS）。

当前阈值基于现有规划参数、合成场景和本开发机历史结果建立，只是软件性能回归线，不是目标服务器生产 SLA。正式数据、正式线路规模和部署硬件到位后，必须重新冻结基线与阈值。

## 2. 当前候选验证结果

2026-09-11在Windows x64、Python 3.12.13干净环境中完成正式范围测试。7/7项测试、9/9次独立执行全部通过，`complete_scope=true`、`accepted=true`，无诊断覆盖，测试前后候选载荷SHA-256均为`ed3446e77f8978827f43f924682f6f41b9ae97b6afd1a501779d8437a92545a0`。

| 测试 | 中位耗时/上限（秒） | 峰值RSS/上限（MB） |
| --- | ---: | ---: |
| 重空网络优化 | 171.139 / 360 | 443.875 / 2048 |
| 滚动优化 | 2.211 / 10 | 78.125 / 1024 |
| 运行图优化 | 19.671 / 60 | 152.371 / 2048 |
| 运行图资源约束 | 2.025 / 10 | 73.418 / 1024 |
| 调度输出链路 | 0.198 / 5 | 20.969 / 512 |
| 历史扰动回放 | 318.892 / 600 | 328.207 / 2048 |
| 联合参数稳健性 | 11.081 / 60 | 82.582 / 2048 |

机器报告和逐轮日志位于`outputs/long_test_performance_gate_py312_20260911/`。该结果证明当前合成范围内没有功能或性能回归，不构成正式数据或目标服务器SLA验收。

## 3. 正式入口

```powershell
python tools/run_long_dispatch_tests.py `
  --output-dir outputs/long_test_performance_gate
```

正式运行必须满足：7项全部执行；不使用`--repeat`或`--timeout-s`覆盖；两个主要热点各独立重复2轮；其余5项各运行1轮。只有报告中的`complete_scope=true`和`accepted=true`同时成立，才表示完整长测性能门禁通过。

单项诊断示例：

```powershell
python tools/run_long_dispatch_tests.py `
  --test heavy_empty_network `
  --output-dir outputs/long_test_heavy_diagnostic
```

单项通过只会产生`selected_scope_passed=true`，不会产生正式的`accepted=true`。

## 4. 冻结配置

阈值位于`release/long_test_performance_gate.json`。每项固定以下字段：

| 字段 | 含义 |
| --- | --- |
| `script` | 被测验证脚本 |
| `timeout_s` | 单轮硬超时；超时后终止完整进程树 |
| `repeat_count` | 正式重复次数 |
| `baseline_median_elapsed_s` | 已验证版本的参考中位耗时，仅用于解释 |
| `max_median_elapsed_s` | 重复测量中位耗时上限 |
| `max_peak_rss_mb` | 所有重复轮次中最大进程树RSS上限 |

门禁阈值特意宽于历史最优值，用于容纳操作系统和共享开发机的正常波动，但会拦截退回优化前数量级的明显回归。不能为了让失败版本通过而临时放宽阈值；应先定位回归原因。确需调整时，要记录同机、固定输入、至少两轮的新证据并升级`gate_version`。

## 5. 输出与失败语义

| 输出 | 用途 |
| --- | --- |
| `long_dispatch_tests.json` | 平台读取的环境、配置版本、逐轮测量、聚合指标和失败原因 |
| `LONG_DISPATCH_TESTS.md` | 人工评审报告 |
| `<test>.run<N>.stdout.txt` | 每项每轮标准输出 |
| `<test>.run<N>.stderr.txt` | 每项每轮错误输出 |

以下任一情况都会使对应测试失败：非零返回码、超时、重复轮次不完整、未取得有效内存样本、中位耗时超限或峰值RSS超限。完整运行中任一测试失败都会使进程返回非零，并使`accepted=false`。

## 6. 发布关系

统一发布验收调用同一运行器，因此长测性能门禁不是额外的旁路报告，而是正式发布的必要门禁。`--skip-long`仍只能用于开发诊断，不能批准发布。
