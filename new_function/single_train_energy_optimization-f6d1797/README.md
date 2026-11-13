# 单列车再生制动能量回收 —— 算法交付包

> 面向前端接入。算法口径已定型，接口与字段以本包 `api_contract.json` 为准。

## 包内结构

```
regenerative_braking/      算法包（dynamics/identification/control/simulation/metrics/io/validation）
run_project.py             命令行入口（跑 6 个基线控制器，输出 CSV/JSON/中文报告）
tools/                     报告生成脚本
configs/data_paths.yaml    数据路径配置（已指向包内数据，开箱可用）
data/single_train/         四类物理参数 JSON（64 个数值字段，全带中文溯源）
data/shared/               共享铁路基础数据子集（只读）
database/                  本模块数据库注释补丁与字段清单
examples/demo_call.py      最小调用示例（跑通即可确认环境正常）
api_contract.json          机器可读接口契约（入口、参数、字段、口径）
docs/                      技术实现方案
前端接入说明.md             接入前必读（给编码代理的结构化说明）
```

## 快速验证

```bash
python -m pip install -r requirements.txt
python examples/demo_call.py
```

退出码 0 表示链路正常；会写出 `demo_output/summary.json` 与 `demo_output/timeseries.csv`。

## 命令行跑基线

```bash
python run_project.py --scenario 1        # 平直制动
python run_project.py --scenario 2        # 长大下坡
```

输出目录含 `README.md`（逐列中文释义）、`summary.csv/json`、`timeseries_*.csv`。

## 三条必须知道的口径

1. 仿真是离线数字仿真，结果不是工程结论；参数带 `data_status` 溯源等级。
2. 评估口径为 `dt = Ts = h = 1e-4 s`；引用能量数字必须同时写明步长。
3. 机读键名保持英文，中文只进说明层；字段译名唯一来源是 `field_label()`。

## 相比早期输出提供的东西

- 控制台、`README.md`、统计报告、图表中的说明文字已全部中文化；机读键名仍为英文。
- 指标表 131 列、时序表 31 列**逐列**有中文名与释义，统一由 `field_label()` 渲染。
- 其中 36 个字段为虚拟值（甲方资料未到位），逐字段清单见 `docs/virtual_data_register_2026-11-05.md`；
- 四个参数文件共 64 个数值字段，全部带中文溯源与 `data_status` 等级。
- 新增 `api_contract.json`：入口签名、控制器目录、14 档场景、参数字段、输出字段、口径纪律一次给全。
- 新增 `examples/demo_call.py`：一条命令验证环境与链路，退出码即结论。

详见 `前端接入说明.md`。
