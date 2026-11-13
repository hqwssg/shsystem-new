"""低维、可解释的 eco-driving 候选优化器。

控制动作只有牵引、惰行、制动及少量等级。实现使用有限宽度的可行状态扩展，
避免把运输组织层的 NSGA-II 混入单列车速度曲线问题。
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_right
import math
from typing import Optional

from ..dynamics.energy_model import EnergyLedger, regen_wheel_force_n
from ..dynamics.train_longitudinal_model import LongitudinalState, integrate_step
from ..models import ControlMode, EcoDrivingResult, EcoDrivingScenario, ProfileSample


@dataclass
class _Node:
    state: LongitudinalState
    ledger: EnergyLedger
    samples: tuple[ProfileSample, ...]
    last_mode: ControlMode
    objective: float
    actions: tuple[tuple[ControlMode, float, float], ...] = ()


class EcoDrivingOptimizer:
    """有限宽度可行状态搜索。

    ``beam_width`` 控制计算量；该算法返回的是可行候选，不宣称全局最优。
    """

    ACTIONS = (
        (ControlMode.TRACTION, 0.20),
        (ControlMode.TRACTION, 0.35),
        (ControlMode.TRACTION, 0.50),
        (ControlMode.TRACTION, 0.75),
        (ControlMode.TRACTION, 1.0),
        (ControlMode.COAST, 0.0),
        (ControlMode.BRAKE, 0.10),
        (ControlMode.BRAKE, 0.25),
        (ControlMode.BRAKE, 0.50),
        (ControlMode.BRAKE, 0.75),
        (ControlMode.BRAKE, 1.0),
    )
    # Speed tracking is a soft objective; endpoint, runtime and speed-limit
    # constraints remain hard gates.  The scale keeps a sustained 1 m/s error
    # material without allowing tracking to overwhelm the energy ledger.
    SPEED_TRACKING_WEIGHT_J_PER_MPS2_S = 20_000.0
    # A traction/brake mode switch is a real operating cost (wear, driver
    # workload, control churn).  Keep it material enough to suppress chatter
    # without blocking necessary traction -> coast -> brake transitions.
    MODE_SWITCH_COST_J = 500_000.0

    def __init__(self, railway, profile, traction_limit_n: Optional[float] = None, beam_width: int = 80, dt: float = 1.0, regen_efficiency: float = 0.85):
        if beam_width < 2 or not math.isfinite(dt) or dt <= 0.0:
            raise ValueError("beam_width 至少为 2，dt 必须为正有限值")
        if not math.isfinite(regen_efficiency) or not 0.0 <= regen_efficiency <= 1.0:
            raise ValueError("regen_efficiency 必须在 [0, 1] 内且为有限值")
        self.railway = railway
        self.profile = profile
        self.traction_limit_n = traction_limit_n
        self.beam_width = beam_width
        self.dt = dt
        self.regen_efficiency = regen_efficiency
        self._segments = tuple(getattr(railway, "segments", ()))
        self._segment_starts = tuple(segment.start_km for segment in self._segments)

    def _segment_at(self, position_km: float):
        """查询单调向前轨迹使用的线路段，避免每个节点线性扫描全线路。"""

        if not self._segments:
            return self.railway.segment_at(position_km)
        index = bisect_right(self._segment_starts, position_km) - 1
        if index < 0 or index >= len(self._segments):
            return None
        segment = self._segments[index]
        if position_km < segment.end_km or index == len(self._segments) - 1 and position_km == segment.end_km:
            return segment
        return None

    def _max_brake_deceleration_mps2(
        self,
        scenario: EcoDrivingScenario,
        position_m: float,
        speed_mps: float,
    ) -> float:
        """Estimate sustainable braking deceleration over the remaining route."""

        max_brake_force = min(
            self.profile.max_brake_force_n,
            self.profile.adhesion.max_brake_force_n(self.profile.mass_kg),
        )
        position_km = scenario.start_km + position_m / 1000.0
        min_gradient = 0.0
        if self._segments:
            start_idx = max(0, bisect_right(self._segment_starts, position_km) - 1)
            end_idx = max(start_idx, bisect_right(self._segment_starts, scenario.end_km) - 1)
            gradients = [
                self._segments[idx].gradient_per_mille
                for idx in range(start_idx, min(len(self._segments), end_idx + 1))
            ]
            if gradients:
                min_gradient = min(gradients)
        else:
            seg = self._segment_at(position_km)
            if seg is not None:
                min_gradient = seg.gradient_per_mille
        terminal_speed = max(0.0, scenario.constraints.terminal_speed_mps)
        avg_speed = 0.5 * (max(0.0, speed_mps) + terminal_speed)
        resistance = (
            self.profile.resistance.force_n(self.profile.mass_kg, avg_speed)
            + self.profile.mass_kg * 9.81 * min_gradient / 1000.0
        )
        decel = (max_brake_force + resistance) / self.profile.effective_mass_kg
        return min(scenario.constraints.max_deceleration_mps2, max(0.02, decel))

    def _expand(self, node: _Node, scenario: EcoDrivingScenario, mode: ControlMode, level: float, step_dt: Optional[float] = None) -> Optional[_Node]:
        position_km = scenario.start_km + node.state.position_m / 1000.0
        segment = self._segment_at(position_km + 1.0e-9)
        if segment is None:
            segment = self._segment_at(position_km)
        if segment is None:
            return None
        gradient = segment.gradient_per_mille
        curve = segment.curve_radius_m
        limit = segment.speed_limit_kmh / 3.6 if segment.speed_limit_kmh else None
        interval_dt = self.dt if step_dt is None else step_dt
        next_state, balance = integrate_step(
            self.profile, node.state, mode, level, interval_dt, gradient, curve,
            scenario.constraints.max_acceleration_mps2,
            scenario.constraints.max_deceleration_mps2,
            self.traction_limit_n,
            boundary_position_m=min(scenario.length_m, (segment.end_km - scenario.start_km) * 1000.0),
        )
        step_dt = next_state.time_s - node.state.time_s
        if next_state.position_m <= node.state.position_m + 1.0e-9:
            return None
        if limit is not None and next_state.speed_mps > limit + 1e-6:
            return None
        remaining_distance = max(0.0, scenario.length_m - next_state.position_m)
        terminal_speed = max(0.0, scenario.constraints.terminal_speed_mps)
        target = scenario.constraints.target_runtime_s
        tolerance = scenario.constraints.runtime_tolerance_s
        is_full_brake = mode is ControlMode.BRAKE and level >= 1.0 - 1.0e-9
        brake_decel = self._max_brake_deceleration_mps2(scenario, next_state.position_m, next_state.speed_mps)
        if target is not None:
            if next_state.time_s > target + tolerance:
                return None
            if remaining_distance > 1.0e-6:
                max_trac_acc = min(
                    scenario.constraints.max_acceleration_mps2,
                    (self.traction_limit_n / self.profile.effective_mass_kg)
                    if self.traction_limit_n is not None
                    else scenario.constraints.max_acceleration_mps2,
                )
                a1 = max(0.02, max_trac_acc)
                a2 = max(0.02, brake_decel)
                v0 = next_state.speed_mps
                v1 = terminal_speed + 0.5
                v_cap = limit if limit is not None else 22.22
                v_peak = min(
                    v_cap,
                    math.sqrt(
                        max(0.0, (2.0 * remaining_distance + (v0 ** 2) / a1 + (v1 ** 2) / a2) / (1.0 / a1 + 1.0 / a2))
                    ),
                )
                d1 = max(0.0, v_peak ** 2 - v0 ** 2) / (2.0 * a1)
                t1 = max(0.0, v_peak - v0) / a1
                d2 = max(0.0, v_peak ** 2 - v1 ** 2) / (2.0 * a2)
                t2 = max(0.0, v_peak - v1) / a2
                d_cruise = max(0.0, remaining_distance - d1 - d2)
                t_cruise = d_cruise / max(0.5, v_peak)
                min_rem_t = t1 + t_cruise + t2
                if next_state.time_s + min_rem_t > target + tolerance:
                    return None
        if remaining_distance > 1.0e-6:
            if remaining_distance > 2.0 and next_state.speed_mps < max(0.25, terminal_speed - 0.25) and mode is ControlMode.BRAKE:
                return None
            max_reachable_speed_sq = (terminal_speed + 0.35) ** 2 + 2.0 * brake_decel * remaining_distance
            if next_state.speed_mps ** 2 > max_reachable_speed_sq and not is_full_brake:
                return None
        elif abs(next_state.speed_mps - terminal_speed) > 0.5 and not is_full_brake:
            return None
        average_speed_step = (node.state.speed_mps + next_state.speed_mps) * 0.5
        traction_power = balance.traction_force_n * average_speed_step
        braking_power = balance.braking_force_n * average_speed_step
        regen_power = regen_wheel_force_n(self.profile, balance.braking_force_n, average_speed_step) * average_speed_step
        ledger = EnergyLedger(
            node.ledger.traction_energy_j,
            node.ledger.mechanical_braking_energy_j,
            node.ledger.available_regenerative_energy_j,
            node.ledger.captured_regenerative_energy_j,
        )
        ledger.add_step(traction_power, braking_power, step_dt, self.regen_efficiency, regen_power_w=regen_power)
        sample = ProfileSample(
            position_m=node.state.position_m,
            time_s=node.state.time_s,
            speed_mps=node.state.speed_mps,
            gradient_per_mille=gradient,
            curve_radius_m=curve,
            speed_limit_mps=limit,
            acceleration_mps2=balance.acceleration_mps2,
            mode=mode,
            traction_force_n=balance.traction_force_n,
            braking_force_n=balance.braking_force_n,
            traction_power_w=traction_power,
            braking_power_w=braking_power,
            cumulative_traction_energy_j=ledger.traction_energy_j,
            cumulative_mechanical_braking_energy_j=ledger.mechanical_braking_energy_j,
            cumulative_regenerative_energy_j=ledger.captured_regenerative_energy_j,
            cumulative_net_energy_j=ledger.net_energy_j,
        )
        switch_cost = self.MODE_SWITCH_COST_J if (node.samples and mode is not node.last_mode) else 0.0
        tracking_penalty = 0.0
        target_speed = scenario.constraints.target_speed_mps
        if target is None and target_speed is not None and target_speed >= 0.0:
            average_speed = (node.state.speed_mps + next_state.speed_mps) * 0.5
            tracking_penalty = self.SPEED_TRACKING_WEIGHT_J_PER_MPS2_S * (
                average_speed - target_speed
            ) ** 2 * step_dt
        return _Node(
            next_state,
            ledger,
            node.samples + (sample,),
            mode,
            node.objective + (ledger.net_energy_j - node.ledger.net_energy_j) + switch_cost + tracking_penalty,
            node.actions + ((mode, min(1.0, max(0.0, level)), step_dt),),
        )

    def _replay_actions(
        self,
        scenario: EcoDrivingScenario,
        actions: tuple[tuple[ControlMode, float, float], ...],
    ) -> Optional[_Node]:
        """Replay a fixed-duration action sequence from the route origin."""

        node = _Node(
            LongitudinalState(0.0, 0.0, scenario.initial_speed_mps),
            EnergyLedger(),
            tuple(),
            ControlMode.COAST,
            0.0,
        )
        for mode, level, interval in actions:
            if node.state.position_m >= scenario.length_m - 1.0e-6:
                break
            child = self._expand(node, scenario, mode, level, interval)
            if child is None or child.state.position_m <= node.state.position_m + 1.0e-9:
                return None
            node = child
        return node

    def _local_refine(self, node: _Node, scenario: EcoDrivingScenario) -> tuple[_Node, int]:
        """Apply bounded coordinate descent around a feasible timed candidate.

        Holding every interval duration fixed while changing a level also
        changes that interval's travelled distance, so the terminal position,
        runtime and terminal speed all drift and the replayed candidate is
        rejected by the endpoint checks.  Instead, keep only the actions
        *before* the perturbed action fixed and re-derive the remaining run
        with the terminal projection, so the endpoint contract is restored
        while a lower traction level can still reduce net energy.

        Each candidate index is perturbed independently from the original
        ``node`` (the projection appends a terminal interval, which changes the
        action layout, so the indices cannot be reused across iterations).  The
        single best improvement across all candidate indices is returned.
        """

        if scenario.constraints.target_runtime_s is None or not node.actions:
            return node, 0
        candidates = [
            index for index, (mode, level, _interval) in enumerate(node.actions)
            if mode is not ControlMode.COAST and 1.0e-6 < level < 1.0 - 1.0e-6
        ]
        candidates = candidates[-8:]
        best = node
        improvements = 0
        for index in candidates:
            mode, level, _interval = node.actions[index]
            # Replay only up to (but not including) the perturbed action, then
            # project the remainder to the terminal contract.
            prefix = node.actions[:index]
            prefix_node = self._replay_actions(scenario, prefix)
            if prefix_node is None:
                continue
            delta = 0.05
            neighbors = tuple(
                sorted({max(0.0, min(1.0, level - delta)), max(0.0, min(1.0, level + delta))})
            )
            for new_level in neighbors:
                # Apply the perturbed action as one interval from the prefix
                # node, then finish with the terminal projection.
                expanded = self._expand(prefix_node, scenario, mode, new_level, _interval)
                if expanded is None or expanded.state.position_m <= prefix_node.state.position_m + 1.0e-9:
                    continue
                candidate = self._terminal_projection(expanded, scenario)
                if candidate is None or self._constraint_violations(candidate, scenario):
                    continue
                if candidate.ledger.net_energy_j + 1.0e-6 < best.ledger.net_energy_j:
                    best = candidate
                    improvements += 1
        return best, improvements

    def _terminal_projection(self, node: _Node, scenario: EcoDrivingScenario) -> Optional[_Node]:
        """Try one physically feasible continuous terminal interval.

        The regular beam expansion uses a fixed ``dt``.  Near the route end
        that discretisation can skip over the only braking window and leave a
        non-zero terminal speed even when a stop is physically reachable.  A
        projection interval is derived from the constant-acceleration
        kinematics for the current railway segment and is accepted only when
        the resulting force remains inside the actuator and acceleration
        limits.  It is a candidate, never a state correction.
        """

        remaining_distance = scenario.length_m - node.state.position_m
        if remaining_distance <= 1.0e-9:
            return None
        segment = self._segment_at(scenario.start_km + node.state.position_m / 1000.0)
        if segment is None:
            return None

        terminal_speed = max(0.0, scenario.constraints.terminal_speed_mps)
        target = scenario.constraints.target_runtime_s
        denominator = node.state.speed_mps + terminal_speed
        ideal_interval = 2.0 * remaining_distance / denominator if denominator > 1.0e-9 else None
        if target is not None:
            remaining_time = target - node.state.time_s
            tolerance = scenario.constraints.runtime_tolerance_s
            if remaining_time + tolerance <= 1.0e-9:
                return None
            min_interval = max(1.0e-6, remaining_time - tolerance)
            max_interval = remaining_time + tolerance
            if remaining_time > 1.0e-9:
                interval = remaining_time
                pred_end_speed = node.state.speed_mps + (
                    2.0 * (remaining_distance - node.state.speed_mps * interval) / (interval ** 2)
                ) * interval
                if abs(pred_end_speed - terminal_speed) > 0.5 and ideal_interval is not None and min_interval <= ideal_interval <= max_interval:
                    interval = ideal_interval
            elif ideal_interval is not None and min_interval <= ideal_interval <= max_interval:
                interval = ideal_interval
            else:
                return None
            desired_acceleration = 2.0 * (
                remaining_distance - node.state.speed_mps * interval
            ) / (interval ** 2)
        else:
            if ideal_interval is None:
                return None
            interval = ideal_interval
            desired_acceleration = (
                terminal_speed ** 2 - node.state.speed_mps ** 2
            ) / (2.0 * remaining_distance)

        resistance = self.profile.resistance.force_n(
            self.profile.mass_kg, node.state.speed_mps
        ) + self.profile.mass_kg * 9.81 * segment.gradient_per_mille / 1000.0
        if segment.curve_radius_m and segment.curve_radius_m > 0.0:
            resistance += self.profile.mass_kg * 9.81 * (600.0 / segment.curve_radius_m) / 1000.0
        coast_acceleration = -resistance / self.profile.effective_mass_kg
        if desired_acceleration >= coast_acceleration:
            if self.traction_limit_n is None:
                return None
            limit = self.traction_limit_n
            force = max(0.0, desired_acceleration * self.profile.effective_mass_kg + resistance)
            mode = ControlMode.TRACTION
        else:
            limit = min(self.profile.max_brake_force_n, self.profile.adhesion.max_brake_force_n(self.profile.mass_kg))
            force = max(0.0, -desired_acceleration * self.profile.effective_mass_kg - resistance)
            mode = ControlMode.BRAKE
        if limit <= 0.0 or force > limit * (1.0 + 1.0e-8):
            return None
        if desired_acceleration > scenario.constraints.max_acceleration_mps2 + 1.0e-8:
            return None
        if desired_acceleration < -scenario.constraints.max_deceleration_mps2 - 1.0e-8:
            return None
        # A projection is meaningful only when the interval stays within the
        # active segment.  Crossing a gradient/curve boundary would violate
        # the constant-resistance assumption; normal beam steps handle that
        # case and can project again from the next segment.
        segment_remaining = max(
            0.0, (segment.end_km - scenario.start_km) * 1000.0 - node.state.position_m
        )
        if remaining_distance > segment_remaining + 1.0e-7:
            return None
        projected = self._expand(node, scenario, mode, min(1.0, force / limit), interval)
        if projected is None or projected.state.position_m < scenario.length_m - 1.0e-6:
            return None
        if self._constraint_violations(projected, scenario):
            return None
        return projected

    def optimize(self, scenario: EcoDrivingScenario, max_steps: int = 2000, *, check=None) -> EcoDrivingResult:
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
            raise ValueError("max_steps 必须为正整数")
        start_segment = self._segment_at(scenario.start_km)
        end_segment = self._segment_at(max(scenario.start_km, scenario.end_km - 1.0e-9))
        if start_segment is None or end_segment is None:
            missing = "线路起点不在共享线路范围" if start_segment is None else "线路终点不在共享线路范围"
            return EcoDrivingResult(tuple(), scenario.data_status, metadata={
                "optimizer": "finite_width_feasible_state_search",
                "feasible_candidate": False,
                "reached_end": False,
                "constraint_violations": (missing,),
                "candidate_count": 0,
            })
        initial = _Node(LongitudinalState(0.0, 0.0, scenario.initial_speed_mps), EnergyLedger(), tuple(), ControlMode.COAST, 0.0)
        beam = [initial]
        completed: list[_Node] = []
        last_nonempty_beam: list[_Node] = [initial]
        pos_bin_m = max(1.0, min(25.0, scenario.length_m / 40.0))
        for _ in range(max_steps):
            if check is not None:
                check()
            expanded: list[_Node] = []
            for node in beam:
                if node.state.position_m >= scenario.length_m - 1.0e-6:
                    completed.append(node)
                    continue
                terminal = self._terminal_projection(node, scenario)
                if terminal is not None:
                    completed.append(terminal)
                for mode, level in self.ACTIONS:
                    child = self._expand(node, scenario, mode, level)
                    if child is not None:
                        if child.state.position_m >= scenario.length_m - 1.0e-6:
                            completed.append(child)
                        else:
                            expanded.append(child)
            if not expanded:
                break
            feasible_completed = [
                node for node in completed if not self._constraint_violations(node, scenario)
            ]
            if len(feasible_completed) >= self.beam_width and scenario.constraints.target_runtime_s is None:
                break
            ordered = sorted(expanded, key=lambda n: self._score(n, scenario))
            if scenario.constraints.target_runtime_s is None:
                buckets: dict[tuple[int, int], _Node] = {}
                for node in ordered:
                    key = (round(node.state.position_m / pos_bin_m), round(node.state.speed_mps * 2.0))
                    buckets.setdefault(key, node)
                selected = list(buckets.values())
                if len(selected) < self.beam_width:
                    seen_ids = {id(item) for item in selected}
                    for node in ordered:
                        if id(node) not in seen_ids:
                            selected.append(node)
                            if len(selected) >= self.beam_width:
                                break
                beam = selected[: self.beam_width]
            else:
                # 目标时分搜索在固定时间步下展开，决定到站时分的是当前位置与当前速度；
                # 按 (位置分箱, 速度分箱) 保留多样化进度候选，避免单标量排序挤掉可行时分轨线。
                buckets = {}
                for node in ordered:
                    key = (round(node.state.position_m / pos_bin_m), round(node.state.speed_mps * 2.0))
                    buckets.setdefault(key, node)
                selected = list(buckets.values())
                if len(selected) < self.beam_width:
                    seen_ids = {id(item) for item in selected}
                    for node in ordered:
                        if id(node) not in seen_ids:
                            selected.append(node)
                            if len(selected) >= self.beam_width:
                                break
                beam = selected[: self.beam_width]
            if beam:
                last_nonempty_beam = beam
        candidates = completed or beam or last_nonempty_beam
        if not candidates:
            return EcoDrivingResult(tuple(), scenario.data_status, metadata={"optimizer": "beam_search", "feasible": False})
        feasible = [node for node in completed if not self._constraint_violations(node, scenario)]
        if feasible:
            best = min(feasible, key=lambda n: (n.ledger.net_energy_j, self._score(n, scenario)))
        else:
            best = min(candidates, key=lambda n: self._score(n, scenario))
        violations = self._constraint_violations(best, scenario)
        local_refinement_attempted = False
        local_refinement_improvements = 0
        if not violations and scenario.constraints.target_runtime_s is not None:
            local_refinement_attempted = True
            best, local_refinement_improvements = self._local_refine(best, scenario)
            violations = self._constraint_violations(best, scenario)
        terminal_samples = self._append_terminal_sample(best, scenario)
        result = EcoDrivingResult(
            terminal_samples,
            scenario.data_status,
            metadata={
                "optimizer": "finite_width_feasible_state_search",
                "beam_width": self.beam_width,
                "dt_s": self.dt,
                "feasible_candidate": not violations and best.state.position_m >= scenario.length_m - 1e-6,
                "reached_end": best.state.position_m >= scenario.length_m - 1e-6,
                "constraint_violations": violations,
                "candidate_count": len(completed),
                "energy": best.ledger.as_dict(),
                "local_refinement_attempted": local_refinement_attempted,
                "local_refinement_improvements": local_refinement_improvements,
            },
        )
        # Baseline is a safety floor for an energy optimizer: when it is
        # feasible under the same constraints and has lower net energy, do not
        # return a beam-search candidate that is demonstrably worse.
        from .baseline import run_baseline
        # Search a small, explicit set of terminal-braking safety margins.
        # This repairs the fixed-step baseline's last-window miss without
        # relaxing endpoint constraints or hiding an infeasible trajectory.
        default_baseline = run_baseline(
            scenario,
            self.railway,
            self.profile,
            dt=self.dt,
            traction_limit_n=self.traction_limit_n,
            regen_efficiency=self.regen_efficiency,
            safety_margin_m=20.0,
        )
        if bool(default_baseline.metadata.get("feasible_candidate", False)):
            baseline_candidates = (default_baseline,)
        else:
            baseline_candidates = (default_baseline,) + tuple(
                run_baseline(
                    scenario,
                    self.railway,
                    self.profile,
                    dt=self.dt,
                    traction_limit_n=self.traction_limit_n,
                    regen_efficiency=self.regen_efficiency,
                    safety_margin_m=margin,
                )
                for margin in (40.0, 60.0, 80.0, 100.0, 120.0, 160.0)
            )
        feasible_baselines = tuple(
            candidate for candidate in baseline_candidates
            if bool(candidate.metadata.get("feasible_candidate", False))
        )
        baseline = min(
            feasible_baselines or baseline_candidates,
            key=lambda candidate: float(
                (candidate.metadata.get("energy") or {}).get("net_energy_kwh", float("inf"))
            ),
        )
        baseline_feasible = bool(
            baseline.metadata.get("feasible_candidate", baseline.metadata.get("reached_end", False))
        )
        if baseline_feasible:
            baseline_energy = float((baseline.metadata.get("energy") or {}).get("net_energy_kwh", float("inf")))
            result_energy = float((result.metadata.get("energy") or {}).get("net_energy_kwh", float("inf")))
            result_feasible = bool(result.metadata.get("feasible_candidate", False))
            # Feasibility is a hard gate.  A lower-energy candidate that misses
            # the route endpoint or terminal speed is not an optimization
            # result; return the feasible baseline first, then compare energy
            # only when both candidates satisfy the same contract.
            if not result_feasible or baseline_energy < result_energy:
                metadata = dict(result.metadata)
                # The returned samples and their metadata must describe the
                # same candidate.  Previously the guard returned the baseline
                # samples while retaining the beam-search candidate's
                # infeasibility flags, so downstream validation could reject a
                # trajectory that was actually feasible.
                baseline_violations = self._result_constraint_violations(baseline, scenario)
                metadata.update({
                    "baseline_guard_selected": True,
                    "optimizer": "finite_width_feasible_state_search+baseline_guard",
                    "feasible_candidate": not baseline_violations,
                    "reached_end": bool(baseline.metadata.get("reached_end")),
                    "constraint_violations": baseline_violations,
                    "candidate_count": int(baseline.metadata.get("steps", 0)),
                    "energy": baseline.metadata.get("energy"),
                    "baseline_safety_margin_m": baseline.metadata.get("safety_margin_m"),
                    "baseline_feasible_candidate_count": len(feasible_baselines),
                })
                return EcoDrivingResult(baseline.samples, baseline.data_status, baseline.disclaimer, metadata)
        metadata = {
            **result.metadata,
            "baseline_guard_selected": False,
            "baseline_safety_margin_m": baseline.metadata.get("safety_margin_m"),
            "baseline_feasible_candidate_count": len(feasible_baselines),
        }
        return EcoDrivingResult(result.samples, result.data_status, result.disclaimer, metadata)

    @staticmethod
    def _constraint_violations(node: _Node, scenario: EcoDrivingScenario) -> tuple[str, ...]:
        violations: list[str] = []
        if node.state.position_m < scenario.length_m - 1e-6:
            violations.append("未到达终点位置")
        # 任意采样点不得超过线路限速（硬约束）；beam 展开只校验区间末速度，
        # 长区间投影可能带着越限速度穿过限速台阶，这里必须逐点复核。
        for index, sample in enumerate(node.samples):
            if sample.speed_limit_mps is not None and sample.speed_mps > sample.speed_limit_mps + 1e-6:
                violations.append(f"第 {index} 点超过限速")
                break
        target = scenario.constraints.target_runtime_s
        if target is not None and abs(node.state.time_s - target) > scenario.constraints.runtime_tolerance_s:
            violations.append(
                f"运行时分超限: actual={node.state.time_s:.3f}s target={target:.3f}s "
                f"tol={scenario.constraints.runtime_tolerance_s:.3f}s"
            )
        if abs(node.state.speed_mps - scenario.constraints.terminal_speed_mps) > 0.5:
            violations.append(
                f"终点速度超限: actual={node.state.speed_mps:.3f}m/s "
                f"target={scenario.constraints.terminal_speed_mps:.3f}m/s"
            )
        return tuple(violations)

    @staticmethod
    def _result_constraint_violations(result: EcoDrivingResult, scenario: EcoDrivingScenario) -> tuple[str, ...]:
        """Apply the same endpoint constraints to a non-search result."""

        if not result.samples:
            return ("轨迹为空",)
        violations: list[str] = []
        if not bool(result.metadata.get("reached_end", False)):
            violations.append("未到达终点")
        for index, sample in enumerate(result.samples):
            if sample.speed_limit_mps is not None and sample.speed_mps > sample.speed_limit_mps + 1e-6:
                violations.append(f"第 {index} 点超过限速")
                break
        target = scenario.constraints.target_runtime_s
        if target is not None and abs(result.runtime_s - target) > scenario.constraints.runtime_tolerance_s:
            violations.append(
                f"运行时分超限: actual={result.runtime_s:.3f}s target={target:.3f}s "
                f"tol={scenario.constraints.runtime_tolerance_s:.3f}s"
            )
        if abs(result.final_speed_mps - scenario.constraints.terminal_speed_mps) > 0.5:
            violations.append(
                f"终点速度超限: actual={result.final_speed_mps:.3f}m/s "
                f"target={scenario.constraints.terminal_speed_mps:.3f}m/s"
            )
        return tuple(violations)

    @staticmethod
    def _append_terminal_sample(node: _Node, scenario: EcoDrivingScenario) -> tuple[ProfileSample, ...]:
        if not node.samples or node.state.position_m < scenario.length_m - 1e-6:
            return node.samples
        last = node.samples[-1]
        if abs(last.position_m - scenario.length_m) <= 1e-6:
            return node.samples
        return node.samples + (ProfileSample(
            position_m=scenario.length_m,
            time_s=node.state.time_s,
            speed_mps=node.state.speed_mps,
            gradient_per_mille=last.gradient_per_mille,
            curve_radius_m=last.curve_radius_m,
            speed_limit_mps=last.speed_limit_mps,
            acceleration_mps2=0.0,
            mode=ControlMode.COAST,
            traction_force_n=0.0,
            braking_force_n=0.0,
            traction_power_w=0.0,
            braking_power_w=0.0,
            cumulative_traction_energy_j=node.ledger.traction_energy_j,
            cumulative_mechanical_braking_energy_j=node.ledger.mechanical_braking_energy_j,
            cumulative_regenerative_energy_j=node.ledger.captured_regenerative_energy_j,
            cumulative_net_energy_j=node.ledger.net_energy_j,
        ),)

    def _score(self, node: _Node, scenario: EcoDrivingScenario) -> float:
        remaining_distance = max(0.0, scenario.length_m - node.state.position_m)
        terminal_speed = max(0.0, scenario.constraints.terminal_speed_mps)
        target = scenario.constraints.target_runtime_s
        if remaining_distance <= 1.0e-6:
            runtime_penalty = 0.0
            if target is not None:
                runtime_error = abs(node.state.time_s - target)
                runtime_excess = max(0.0, runtime_error - scenario.constraints.runtime_tolerance_s)
                runtime_penalty = 500_000.0 * runtime_error + 1.0e12 * runtime_excess
            terminal_error = abs(node.state.speed_mps - terminal_speed)
            terminal_excess = max(0.0, terminal_error - 0.5)
            terminal_penalty = 1.0e9 * terminal_error + 1.0e12 * terminal_excess
            return node.objective + runtime_penalty + terminal_penalty

        brake_decel = self._max_brake_deceleration_mps2(scenario, node.state.position_m, node.state.speed_mps)
        max_reachable_speed_sq = (terminal_speed + 0.35) ** 2 + 2.0 * brake_decel * remaining_distance
        envelope_excess = max(0.0, node.state.speed_mps ** 2 - max_reachable_speed_sq)
        envelope_penalty = 1.0e12 * envelope_excess

        ref_decel = max(0.05, 0.75 * brake_decel)
        if target is not None:
            # Construct a physically consistent cruise-then-brake reference profile
            # (t_ref(p), v_ref(p)) that reaches (length_m, target, terminal_speed).
            b_term = ref_decel * target + terminal_speed
            disc = b_term ** 2 - (2.0 * ref_decel * scenario.length_m + terminal_speed ** 2)
            if disc >= 0.0:
                v_nom = max(0.5, b_term - math.sqrt(disc))
                d_brake = max(0.0, v_nom ** 2 - terminal_speed ** 2) / (2.0 * ref_decel)
            else:
                v_nom = max(0.5, scenario.length_m / max(1.0, target))
                d_brake = max(0.0, scenario.initial_speed_mps ** 2 - terminal_speed ** 2) / (2.0 * ref_decel)
            if remaining_distance <= max(d_brake * 1.35, 60.0):
                est_rem_time = 2.0 * remaining_distance / max(0.5, node.state.speed_mps + terminal_speed)
                est_arrival_s = node.state.time_s + est_rem_time
                runtime_penalty = 500_000.0 * abs(est_arrival_s - target)
                return node.objective + runtime_penalty + envelope_penalty
            potential_regen_j = (
                self.regen_efficiency
                * 0.5
                * self.profile.effective_mass_kg
                * max(0.0, node.state.speed_mps ** 2 - terminal_speed ** 2)
            )
            effective_objective = node.objective - potential_regen_j
            v_ref = v_nom
            t_brake = max(0.0, v_nom - terminal_speed) / ref_decel if d_brake > 1.0e-9 else 0.0
            rem_t_ref = (remaining_distance - d_brake) / v_nom + t_brake
            t_ref = target - rem_t_ref
            time_error = abs(node.state.time_s - t_ref)
            speed_error = abs(node.state.speed_mps - v_ref)
            runtime_penalty = 50_000_000.0 * time_error + 25_000_000.0 * speed_error
            return effective_objective + runtime_penalty + envelope_penalty

        distance_penalty = remaining_distance * 1.0e8
        progress = 0.0
        if scenario.length_m > 1.0e-9:
            progress = min(1.0, max(0.0, node.state.position_m / scenario.length_m))
        terminal_weight = progress ** 4
        terminal_penalty = (
            abs(node.state.speed_mps - terminal_speed)
            * 1.0e8
            * terminal_weight
        )
        return node.objective + distance_penalty + terminal_penalty + envelope_penalty
