"""搜索、结构修复和精确求解共用的可选试验预算；不改变默认生产入口。"""
from contextlib import contextmanager
import math
import time


class WorkBudgetReached(Exception):
    """计算停止只表示预算用尽，不证明模型无解。"""


class WorkPhaseReached(WorkBudgetReached):
    """阶段份额用尽，剩余全局预算仍可交给后续阶段。"""


class RecoveryWorkBudget:
    def __init__(self, *, full_limit, resource_limit, candidate_limit, wall_limit_s, solver_limit_s):
        for name, value in (("full_limit", full_limit), ("resource_limit", resource_limit), ("candidate_limit", candidate_limit)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name}必须是正整数")
        for value in (wall_limit_s, solver_limit_s):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("时间预算必须是有限正数")
        self.started = time.perf_counter()
        self.deadline = self.started + wall_limit_s
        self.full_limit, self.resource_limit, self.candidate_limit = full_limit, resource_limit, candidate_limit
        self.solver_limit_s = solver_limit_s
        self.full_count = self.resource_count = self.solver_calls = 0
        self.solver_time_s = 0.0
        self.candidates = set()
        self.stage = "setup"
        self.stage_ceiling = None
        self.trace = []

    def check(self):
        if time.perf_counter() >= self.deadline:
            raise WorkBudgetReached("wall_time_budget")

    @contextmanager
    def phase(self, name, resource_limit=None):
        previous = self.stage, self.stage_ceiling
        self.stage, self.stage_ceiling = name, None if resource_limit is None else self.resource_count + resource_limit
        self.trace.append({"event": "phase_start", "stage": name, "elapsed_s": time.perf_counter() - self.started})
        try:
            self.check()
            yield
        finally:
            self.trace.append({"event": "phase_end", "stage": name, "elapsed_s": time.perf_counter() - self.started})
            self.stage, self.stage_ceiling = previous

    def candidate(self, key):
        self.check()
        if key not in self.candidates:
            if len(self.candidates) >= self.candidate_limit:
                raise WorkBudgetReached("candidate_budget")
            self.candidates.add(key)
            self.trace.append({"event": "candidate", "stage": self.stage, "key": key})

    def resource(self, count=1):
        if type(count) is not int or count <= 0:
            raise ValueError("资源检查次数必须是正整数")
        self.check()
        if self.resource_count + count > self.resource_limit:
            raise WorkBudgetReached("resource_check_budget")
        if self.stage_ceiling is not None and self.resource_count + count > self.stage_ceiling:
            raise WorkPhaseReached("phase_resource_budget")
        self.resource_count += count
        self.trace.append({"event": "resource", "stage": self.stage, "count": count})

    def full(self, scenario_count):
        self.check()
        if self.full_count >= self.full_limit:
            raise WorkBudgetReached("full_evaluation_budget")
        self.resource(scenario_count)
        self.full_count += 1
        self.trace.append({"event": "full", "stage": self.stage, "count": 1})

    def begin_solver(self, requested_s):
        self.check()
        limit = min(float(requested_s), self.solver_limit_s - self.solver_time_s, self.deadline - time.perf_counter())
        if limit <= .01:
            raise WorkBudgetReached("solver_time_budget")
        self.solver_calls += 1
        self.trace.append({"event": "solver", "stage": self.stage, "limit_s": limit})
        return limit

    def finish_solver(self, elapsed_s):
        if not math.isfinite(elapsed_s) or elapsed_s < 0:
            raise ValueError("求解器耗时必须有限且非负")
        self.solver_time_s += elapsed_s
        self.trace.append({"event": "solver_finish", "stage": self.stage, "elapsed_s": elapsed_s})

    def snapshot(self):
        return dict(full_count=self.full_count, full_limit=self.full_limit, resource_count=self.resource_count,
                    resource_limit=self.resource_limit, candidate_count=len(self.candidates), candidate_limit=self.candidate_limit,
                    solver_calls=self.solver_calls, solver_time_s=self.solver_time_s, solver_limit_s=self.solver_limit_s,
                    wall_time_s=time.perf_counter() - self.started, trace=self.trace)
