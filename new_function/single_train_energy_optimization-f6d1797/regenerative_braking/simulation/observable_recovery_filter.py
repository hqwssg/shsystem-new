"""显式研究：用上一拍可观测残差及投影参考选择静稳恢复方式。"""
import numpy as np

from .controllers import ControllerError
from .noise_shape_filter import NoiseShapeFilter


def choose_voltage_memory(mode, raw, filtered, reference, lower, upper):
    """保留条件只用符号、参考方向及已有投影边界；无对象真值输入。"""
    positive = raw > filtered
    headroom = reference < upper - 1e-7 and upper > lower
    reference_driving = headroom and reference >= filtered
    if mode == 'residual':
        return positive
    if mode == 'reference':
        return reference_driving
    if mode == 'joint':
        return positive and reference_driving and reference <= raw
    raise ControllerError('未知可观测恢复规则')


class ObservableRecoveryFilter(NoiseShapeFilter):
    """先完成过去静稳检测，再选择保持预测状态或立即重锚。

    keep只允许静稳alpha=.05；参考由既有ReferenceConstraintFeedback在本拍
    控制之后回送，下一拍才消费。无有效上拍参考时采用立即重锚。
    该规则为assumed研究假设，默认工厂不装配。
    """

    def __init__(self, *, recovery_selection='joint', **kwargs):
        if recovery_selection not in ('residual', 'reference', 'joint'):
            raise ControllerError('未知可观测恢复规则')
        if kwargs.get('recovery_voltage_alpha') != kwargs.get('voltage_alpha', .05):
            raise ControllerError('可观测恢复的保持分支必须使用静稳校正系数')
        self.recovery_selection = recovery_selection
        super().__init__(**kwargs)

    def clear_constraint_memory(self):
        super().clear_constraint_memory()
        self._recovery_reference = None

    def clear(self):
        super().clear()
        self._recovery_measurement = None

    def reset(self):
        super().reset()
        self.recovery_decisions = []

    def observe_reference(self, voltage, lower, upper, power):
        super().observe_reference(voltage, lower, upper, power)
        if power > 0 and upper > lower:
            self._recovery_reference = (self._time_s, voltage, lower, upper)

    def _release_voltage_state(self):
        sample, reference = self._recovery_measurement, self._recovery_reference
        valid = (sample is not None and reference is not None and
                 sample[0] == reference[0] == self._time_s)
        keep = bool(valid and choose_voltage_memory(self.recovery_selection, *sample[1:], *reference[1:]))
        # 记录的输入严格来自过去拍；本拍量测只在父类稍后校正时消费。
        self.recovery_decisions.append((self._decision_time,
            *(sample if sample is not None else (np.nan,)*3),
            *(reference if reference is not None else (np.nan,)*4), int(valid), int(keep),
            self._state[0]+self.sample_time_s/self.output_capacitance_f*(
                (1-self._d2)*self._state[1]-self._state[2])))
        if keep:
            super()._release_voltage_state()
        else:
            self._state = None
            self._recovery_ramp_remaining = 0

    def apply(self, observation):
        self._decision_time = observation.time_s
        processed = super().apply(observation)
        self._recovery_measurement = ((observation.time_s, observation.output_voltage_v, processed.output_voltage_v)
            if self._state is not None else None)
        return processed

    def audit(self):
        return dict(**super().audit(), observable_recovery=dict(
            rule=self.recovery_selection, data_status='assumed', review_required=True,
            timing='使用上拍原始电压减滤波电压的残差，以及上拍投影参考',
            missing_reference='立即重新锚定电压',
            keep_events=sum(r[9] for r in self.recovery_decisions),
            instant_events=sum(1-r[9] for r in self.recovery_decisions),
            limitation='残差符号与参考联合规则为研究假设；不读取电阻电感真值、噪声元数据或未来量测'))
