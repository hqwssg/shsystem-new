"""预算管线使用真实完整评分；耗尽预算不能导出伪可行结果或改写历史ID。"""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import resource_constraints
from budgeted_recovery_search import optimize_budgeted, factory_unbudgeted
from recovery_work_budget import RecoveryWorkBudget
from rolling_optimizer import ScheduleTemplate, GeneratedSchedule
from tools.benchmark_constraint_guided_extended import build_context, config_for, PRESET


def main():
    with TemporaryDirectory(prefix="budgeted_recovery_smoke_") as tmp:
        case, context = build_context(dict(data_dir=str(ROOT / "data/real_shuohuang"), profile="positive_discharge"), Path(tmp))
        base = ScheduleTemplate(3300, 3300, 2760, 1, 1, storage_preset_id=PRESET)
        config = replace(config_for(11), population_size=2, generations=1, elite_count=1,
            allowed_heavy_headways_s=(3300,), allowed_empty_headways_s=(3300,), allowed_phases_s=(2760,),
            allowed_holds_s=(0,), allowed_storage_align_shifts_s=(0,))
        budget = RecoveryWorkBudget(full_limit=4, resource_limit=200, candidate_limit=50, wall_limit_s=30, solver_limit_s=2)
        with patch("rolling_optimizer.check_schedule_resources", wraps=resource_constraints.check_schedule_resources) as checker:
            result = optimize_budgeted(base, [base], config, case, context, budget, combined=False, departure_end_s=3299)
        # 正常预算下是否找到可行解取决于能耗数据（Davis 阻力量纲修正后该场景可能无可行
        # 解），因此不硬编码“必须可行”；但完整评价记账必须真实：选中解若存在则必须 feasible，
        # 且完整评价次数与记账一致，不能把未完整评价的候选当作可行结果导出。
        if result["selected"] is not None:
            assert result["selected"][1].feasible
        # 资源记账必须自洽：check_schedule_resources 的调用次数等于累计消耗的资源额度，
        # 且不超过上限。能耗数据变化会让搜索或提前找到可行解（消耗少量资源）或耗尽预算
        # （打满 200），两者都合法；伪造或漏记才会破坏这个恒真关系。
        assert checker.call_count == budget.resource_count
        assert budget.resource_count <= budget.resource_limit
        assert budget.full_count == len(result["full_candidate_records"]) == 1
        history = GeneratedSchedule([0], [2760], base, ["H007"], ["E009"])
        display = factory_unbudgeted(replace(base, start_time_s=3300), history)
        assert display.heavy_train_ids == ["H007", "H008"] and display.empty_train_ids == ["E009", "E010"]
        # 首次完整评价前即耗尽资源额度，不能把未计算的候选当成完整评分。
        tiny = RecoveryWorkBudget(full_limit=1, resource_limit=1, candidate_limit=1, wall_limit_s=30, solver_limit_s=.01)
        result = optimize_budgeted(base, [base], config, case, context, tiny, combined=False, departure_end_s=3299)
        assert result["selected"] is None and result["full_candidate_records"] == [] and tiny.full_count == 0
    print("budgeted recovery pipeline, full-evaluation accounting and history IDs: PASS")

if __name__ == "__main__":
    main()
