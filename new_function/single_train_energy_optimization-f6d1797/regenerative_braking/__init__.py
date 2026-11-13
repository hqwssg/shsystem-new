"""单列车再生制动能量回收算法包。

技术方案对应章节：4.2.1.3「朔黄铁路列车再生制动能量回收研究」。

总体控制链（不可替换）：

    列车制动工况
    -> 牵引电机产生再生能量
    -> 双向 DC-DC 变换器
    -> 储能系统
    -> RHONN 状态辨识
    -> EKF / UKF 在线更新 RHONN 参数
    -> NSMC 计算控制量
    -> T1/T2 PWM 占空比
    -> 调节 DC-DC 功率流
    -> 稳定电压、电流、回收功率和 SOC

当前实现进度：阶段 1（物理仿真底座）+ 阶段 2（固定占空比 baseline）。
"""

__all__ = [
    "dynamics",
    "identification",
    "control",
    "simulation",
    "metrics",
    "io",
    "validation",
]

__version__ = "0.1.0"
