# 干净环境与可移植性验证

## 1. 目的

本验证用于证明算法软件不依赖开发机已有虚拟环境、用户级Python包、历史输出、论文实验目录、原始甲方文件或固定用户路径。它不评价正式节能率，也不替代目标平台和正式数据验收。

## 2. 当前实现

- Python支持范围：`>=3.11,<3.13`；已安装并验证CPython 3.11.15和3.12.13；
- `requirements.txt`保存直接依赖版本，`requirements-lock.txt`保存19个直接及传递依赖及其制品SHA-256；
- 发布白名单排除一次性Word构建器、原始数据、历史输出、论文目录、参考资料和归档材料；
- smoke所需基线和样本均位于`tests/fixtures`或由测试临时生成，不再读取包外历史结果和大体积原始电表；
- 文档生成工具不再写死开发机用户名和版本目录，可通过`ENERGY_RETRY_DOCUMENT_SKILL_SCRIPTS`配置，仅用于文档开发，不属于算法发布载荷。

## 3. 验证矩阵

`tools/clean_environment_portability.py`执行以下检查：

1. 校验`release/accepted_release.json`绑定的正式ZIP SHA-256并安全解压；
2. 按当前发布白名单复制候选快照；
3. 为Python 3.11和3.12分别创建全新虚拟环境，禁用用户site-packages；
4. 安装依赖并记录完整包清单；当前候选使用`--require-hashes`；
5. 对正式v5和当前候选分别执行项目编译、7项关键smoke和最小重空调度；
6. 从项目外中立工作目录启动调度，输入和输出路径包含中文及空格；
7. 比较运行前后载荷文件哈希，拒绝源文件被运行过程修改；
8. Python 3.11和3.12均在指定候选ZIP解压根目录执行96项默认短测；当前源码副本另执行代表性检查，用于发现构建前后差异。

运行命令：

```powershell
python tools/clean_environment_portability.py
```

网络较慢且已完成一次无缓存安装证明后，可使用`--allow-download-cache`复用下载文件；该选项仍创建全新虚拟环境并执行依赖哈希校验。

## 4. 当前证据

- 可移植性报告：`outputs/clean_environment_portability_20260911/clean_environment_portability.json`；
- 人工阅读报告：`outputs/clean_environment_portability_20260911/CLEAN_ENVIRONMENT_PORTABILITY_REPORT.md`；
- 最新软件成分审计：`outputs/security_audit_20260913_v1/`；
- Python 3.12独立长测：`outputs/long_test_performance_gate_py312_20260911/`，7/7项、9/9次执行通过，完整门禁接受；
- 当前候选审计：19个组件，OSV查询19/19成功，已知漏洞0、未知许可证0、阻断项0；
- CycloneDX 1.6官方schema验证通过。

## 5. 结论边界

本轮只在Windows x64执行。Linux/macOS、目标服务器Python发行方式、内部制品仓库、真实PostgreSQL网络、平台任务队列、正式数据和现场性能尚未验证。指定候选包存在`requirements-lock.txt`时，Python 3.11和3.12均必须通过`--require-hashes`安装；旧包缺少锁文件时只能形成兼容性诊断，不能据此批准新正式版本。新候选仍必须完成双版本短测、独立长测和统一发布验收。
