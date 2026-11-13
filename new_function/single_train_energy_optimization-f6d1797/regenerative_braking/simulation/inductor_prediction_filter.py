"""显式研究候选：过去已执行PWM预推电感电流，再用同拍电流量测校正。"""
from dataclasses import replace

import numpy as np

from .capacitor_voltage_filter import CapacitorVoltageFilter
from .controllers import ControllerError


class InductorPredictionFilter(CapacitorVoltageFilter):
    """原电容/Vin预处理上增加因果电感预测；不改真实状态或储能边界。

    i_pred=max(0,i_previous+Ts/L_nom*(d1*Vin_previous-(1-d2)*Vout_previous-RL_nom*i_previous))。
    电流校正为 alpha*i_measured+(1-alpha)*i_pred；预测非负来自原平均模型续流二极管。
    shared_capacitor_current控制下一拍电容预测使用处理后的还是原始过去电流，供消融。
    L/RL/C仍为placeholder/assumed；禁止向控制器传真实对象的扰动参数。
    """

    def __init__(self, *, inductance_h, inductor_resistance_ohm, current_alpha=.1,
                 shared_capacitor_current=False, **kwargs):
        for name, value in (("inductance_h", inductance_h), ("inductor_resistance_ohm", inductor_resistance_ohm),
                            ("current_alpha", current_alpha)):
            if isinstance(value, (bool, np.bool_)) or not np.isfinite(value) or value < 0:
                raise ControllerError(f"{name}必须为有限非负数，不能为布尔值")
        if inductance_h == 0 or not 0 < current_alpha <= 1:
            raise ControllerError("电感必须为正，电流校正系数必须在(0,1]内")
        if not isinstance(shared_capacitor_current, bool):
            raise ControllerError("shared_capacitor_current必须为bool")
        self.inductance_h = float(inductance_h)
        self.inductor_resistance_ohm = float(inductor_resistance_ohm)
        self.current_alpha = float(current_alpha)
        self.shared_capacitor_current = shared_capacitor_current
        super().__init__(**kwargs)

    def clear(self):
        super().clear()
        self._electrical = None
        self._d1 = None

    def reset(self):
        super().reset()
        self.current_prediction_steps = 0
        self.diode_projection_steps = 0

    def accept_applied_command(self, command):
        if not np.isfinite(command.duty_cycle_T1) or not 0 <= command.duty_cycle_T1 <= 1:
            raise ControllerError("电感预测需要合法已执行T1占空比")
        super().accept_applied_command(command)
        self._d1 = float(command.duty_cycle_T1)

    def _prediction_weights(self):
        """显式研究子类可用过去可见信息连续混合；原类逐位保留原路径。"""
        return 1., float(self.shared_capacitor_current)

    def apply(self, observation):
        # super执行原始量测/时间校验及缺测/拒充/时间缺口重锚；其预测只用过去样本。
        processed = super().apply(observation)
        if self._state is None:
            return processed
        current_weight, capacitor_weight = self._prediction_weights()
        current = observation.inductor_current_a
        if self._electrical is not None and self._d1 is not None and self._d2 is not None:
            vin, vout, previous = self._electrical
            raw = previous+self.sample_time_s/self.inductance_h*(
                self._d1*vin-(1-self._d2)*vout-self.inductor_resistance_ohm*previous)
            self.diode_projection_steps += int(raw < 0)
            predicted = max(0., raw)
            corrected = self.current_alpha*current+(1-self.current_alpha)*predicted
            if current_weight == 1.:
                current = corrected
            elif current_weight > 0.:
                current += current_weight*(corrected-current)
            if not np.isfinite(current):
                raise ControllerError("电感预测结果必须有限")
            self.current_prediction_steps += 1
        self._electrical = (processed.input_voltage_v, processed.output_voltage_v, float(current))
        if capacitor_weight == 1.:
            self._state = (self._state[0], float(current), self._state[2])
        elif capacitor_weight > 0.:
            shared = observation.inductor_current_a+capacitor_weight*(current-observation.inductor_current_a)
            self._state = (self._state[0], float(shared), self._state[2])
        return replace(processed, inductor_current_a=float(current))

    def audit(self):
        payload = super().audit()
        payload["current_channels"] = "电感电流采用预测与校正，输出电流使用原始量测"
        return dict(**payload, current_prediction=dict(
            kind="inductor_prediction_correction", data_status="derived", review_required=True,
            inductance_h=self.inductance_h, inductor_resistance_ohm=self.inductor_resistance_ohm,
            parameter_status="placeholder/assumed", current_alpha=self.current_alpha,
            shared_capacitor_current=self.shared_capacitor_current,
            prediction_steps=self.current_prediction_steps, diode_projection_steps=self.diode_projection_steps,
            timing="使用上拍处理后的输入电压、输出电压、电感电流及已执行占空比预测，以本拍电感电流校正"))
