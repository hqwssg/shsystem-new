"""按电容平衡预测、当前量测校正的显式因果预处理候选。"""
from dataclasses import replace

import numpy as np

from .controllers import ControllerError
from .electrical_measurement_filter import ElectricalMeasurementFilter, ELECTRICAL_CHANNELS


class CapacitorVoltageFilter:
    """Vout预测使用过去的原始电流与已执行T2，Vin采用原一阶IIR。

    v_pred=v_previous+Ts/C_nom*((1-d2_previous)*iL_previous-iout_previous)
    v_filtered=alpha*v_measured+(1-alpha)*v_pred。
    不是新的RHONN或状态EKF；所有控制/辨识仍共享同一处理观测。
    C_nom依赖placeholder，alpha为assumed；不宣称任意对象下最优或稳定。
    """

    def __init__(self, *, sample_time_s, output_capacitance_f, voltage_alpha=.1, input_voltage_alpha=.5):
        for name, value in (("sample_time_s",sample_time_s),("output_capacitance_f",output_capacitance_f)):
            if isinstance(value,(bool,np.bool_)) or not np.isfinite(value) or value<=0:
                raise ControllerError(f"{name}必须为正有限数，不能为布尔值")
        if isinstance(voltage_alpha,(bool,np.bool_)) or not np.isfinite(voltage_alpha) or not 0<voltage_alpha<=1:
            raise ControllerError("电容电压校正系数必须为(0,1]内有限数")
        self.sample_time_s=float(sample_time_s)
        self.output_capacitance_f=float(output_capacitance_f)
        self.voltage_alpha=float(voltage_alpha)
        self.input_filter=ElectricalMeasurementFilter(alpha=input_voltage_alpha,sample_time_s=sample_time_s,
            channels=("input_voltage_v",))
        self.reset()

    def clear(self):
        self._state=None
        self._time_s=None
        self._d2=None
        self.input_filter.clear()

    def reset(self):
        self.clear()
        self.input_filter.reset()
        self.updates=0
        self.reanchors=0
        self.prediction_steps=0

    def accept_applied_command(self, command):
        value=command.duty_cycle_T2
        if not np.isfinite(value) or not 0<=value<=1:
            raise ControllerError("电容预测需要合法已执行T2占空比")
        self._d2=float(value)

    def apply(self, observation):
        if not observation.electrical_measurement_valid or observation.storage_charge_power_limit_w==0:
            self.clear()
            return observation
        values=np.array([getattr(observation,key) for key in ELECTRICAL_CHANNELS],dtype=float)
        time_s=float(observation.time_s)
        if not np.all(np.isfinite(values)) or not np.isfinite(time_s) or np.any(values[:2]<=0) or np.any(values[2:]<0):
            raise ControllerError("电容预测不能掩盖非法电气量测或时间")
        if self._time_s is not None:
            interval=time_s-self._time_s
            if interval<=0:
                raise ControllerError("电容预测的时间必须严格递增")
            if interval>self.sample_time_s*(1+1e-7):
                self.clear()
        if self._state is None or self._d2 is None:
            voltage=values[1]
            self.reanchors+=1
        else:
            previous_voltage,previous_inductor,previous_sink=self._state
            predicted=previous_voltage+self.sample_time_s/self.output_capacitance_f*(
                (1-self._d2)*previous_inductor-previous_sink)
            voltage=self.voltage_alpha*values[1]+(1-self.voltage_alpha)*predicted
            if not np.isfinite(voltage) or voltage<=0:
                raise ControllerError("电容预测校正结果非法；拒绝静默限幅")
            self.prediction_steps+=1
        self._state=(float(voltage),float(values[2]),float(values[3]))
        self._time_s=time_s
        self.updates+=1
        processed=self.input_filter.apply(observation)
        return replace(processed,output_voltage_v=float(voltage))

    def audit(self):
        return dict(kind="capacitor_voltage_prediction_correction",data_status="derived",review_required=True,
            voltage_alpha=self.voltage_alpha,parameter_status="assumed",sample_time_s=self.sample_time_s,
            output_capacitance_f=self.output_capacitance_f,capacitance_status="placeholder",
            input_voltage_filter=self.input_filter.audit(),current_channels="raw",updates=self.updates,
            reanchors=self.reanchors,prediction_steps=self.prediction_steps,
            timing="使用上拍电流与已执行的第二路占空比预测，以本拍电压校正；各模块共享处理后的观测")
