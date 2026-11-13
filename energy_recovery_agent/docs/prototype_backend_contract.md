# 原型与后端契约

机器可读契约位于 `docs/prototype_backend_contract.json`。它定义原型字段的 UI ID、字段性质、正式 CLI 映射、是否可编辑和输出必备字段。

运行校验：

```powershell
python tools/validate_prototype_contract.py
```

当前契约将字段分为：版本引用、单次场景控制、自动派生只读字段、离线测试占位字段。原型中的晚点、天气和设备退出选项已标记为待后端场景模型，不能直接提交正式算法。正式后端结果至少应返回运行 ID、输入快照、代码快照摘要、校验状态、结果质量状态、指标和制品清单。
