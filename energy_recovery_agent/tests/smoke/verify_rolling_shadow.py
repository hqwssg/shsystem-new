"""影子入口、身份、预算、DB投影及不可执行标志的正反向回归。"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from database.parameters import validate_run_parameters
from database.worker import build_algorithm_command,execute_claimed_run
from database.postgres import SimulationRepository
from database.snapshots import record_from_bytes
from database.solver_budget import build_solve_attempts
from database.result_projection import project_result_directory
from rolling_shadow import run_shadow, load_shadow_request, validate_shadow_output


def rejected(fn):
    try:
        fn()
    except (ValueError, TypeError, FileNotFoundError):
        return
    raise AssertionError("危险或未批准输入必须拒绝")


def main():
    params = dict(experimental_budgeted_shadow=True, shadow_request_relative_path="shadow.json")
    validate_run_parameters("rolling_rescheduling", params)
    for bad in ({"shadow_request_relative_path":"shadow.json"},
                {"experimental_budgeted_shadow":True},
                {**params,"experimental_budgeted_shadow":"true"},
                {**params,"shadow_request_relative_path":"../escape.json"},
                {**params,"disable_recovery":False},
                {**params,"storage_devices":[]}):
        rejected(lambda: validate_run_parameters("rolling_rescheduling",bad))
        rejected(lambda: SimulationRepository(object()).create_run(project_id=uuid4(),version_id=uuid4(),
            run_type="rolling_rescheduling",parameters=bad,idempotency_key="unsafe-enqueue"))
    assert len(build_solve_attempts("rolling_rescheduling",params)) == 1
    assert len(build_solve_attempts("rolling_rescheduling",{})) >= 2
    with TemporaryDirectory(prefix="shadow_regression_") as name:
        work = Path(name)
        p = json.loads((ROOT / "data_templates/rolling_shadow_request_template.json").read_text(encoding="utf-8"))
        p["cycles"] = p["cycles"][:2]
        p["cycles"][0]["new_services"] = p["cycles"][0]["new_services"][:2]
        p["cycles"][1].pop("cancelled_train_ids",None)
        path = work / "shadow.json"
        def save(payload):
            path.write_text(json.dumps(payload),encoding="utf-8")
        save(p)
        command = build_algorithm_command("rolling_rescheduling",params,data_dir=work,output_dir=work/"out")
        assert "rolling-budgeted-shadow" in command and "--experimental-budgeted-shadow" in command
        assert "benchmark-rolling-rescheduling" in build_algorithm_command("rolling_rescheduling",{},data_dir=work,output_dir=work/"legacy")
        # 即使错误子进程声称成功，worker也不能把普通输出当成影子结果持久化。
        class FakeRepository:
            persisted=False
            failed=False
            def load_version_files(self,*args):return (record_from_bytes("shadow.json",json.dumps(p).encode()),)
            def load_storage_device_parameters(self,*args):return ({"storage_section_id":"test"},)
            def freeze_run_snapshot(self,*args,**kwargs):pass
            def heartbeat_run(self,*args,**kwargs):pass
            def persist_result(self,*args,**kwargs):self.persisted=True
            def mark_failed(self,*args,**kwargs):self.failed=True
        def wrong_runner(command,cwd):
            dest=Path(command[command.index("--output-dir")+1]);dest.mkdir(parents=True)
            (dest/"summary.json").write_text('{"optimization_decision":{"action":"optimize"}}',encoding="utf-8")
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0,stdout="",stderr="")
        repo=FakeRepository()
        rejected(lambda:execute_claimed_run(repo,dict(run_id=uuid4(),version_id=uuid4(),worker_id="test-shadow",
            lease_token=uuid4(),run_type="rolling_rescheduling",parameters=params),runner=wrong_runner))
        assert repo.failed and not repo.persisted
        for mutate in (
            lambda q:q.update(mode="live"),
            lambda q:q["cycles"][1].update(current_time_s=3301),
            lambda q:q["cycles"][1].update(cancelled_train_ids=["H001"]),
            lambda q:q["cycles"][1]["new_services"][0].update(train_id="H001"),
            lambda q:q.update(budget={"full_limit":100000}),
            lambda q:q["cycles"][0].update(allow_dispatch=True)):
            bad=deepcopy(p); mutate(bad); save(bad); rejected(lambda:load_shadow_request(path))
        save(p)
        rejected(lambda:run_shadow(data_dir=ROOT/"data/real_shuohuang",request_path=path,output_dir=work/"off"))
        summary=run_shadow(data_dir=ROOT/"data/real_shuohuang",request_path=path,output_dir=work/"on",
            experimental_budgeted_shadow=True,population_size=2,generations=1,job_wall_limit_s=60)
        assert summary["shadow_only"] and not summary["execution_allowed"] and summary["cycle_count"]==2
        projected=project_result_directory(uuid4(),work/"on")
        assert projected["decision"]["action"]=="keep_baseline" and not projected["decision"]["execution_allowed"]
        assert projected["rolling_control_events"]==projected["candidates"]==projected["running_arcs"]==[]
        rows=json.loads((work/"on/shadow_cycles.json").read_text(encoding="utf-8"))
        assert all(row["requested_train_ids"]==[f"H00{i+1}",f"E00{i+1}"] for i,row in enumerate(rows))
        assert rows[1]["carried_soc_by_storage_kwh"]==rows[0]["executed_final_soc_by_storage_kwh"]
        (work/"on/rolling_cycles.csv").write_text("malicious normal output",encoding="utf-8")
        rejected(lambda:validate_shadow_output(work/"on"))
    print("budgeted rolling shadow switch, identity, state continuity and non-dispatch projection: PASS")

if __name__=="__main__":
    main()
