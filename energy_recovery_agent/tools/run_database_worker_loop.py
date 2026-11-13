"""以可停止的轮询循环运行数据库算法工作进程。"""

from __future__ import annotations

from typing import Sequence
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres import SimulationRepository, connect_postgres
from database.worker import run_one_pending


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("SIMULATION_DATABASE_URL"))
    parser.add_argument("--worker-id", default=os.environ.get("SIMULATION_WORKER_ID"))
    parser.add_argument(
        "--poll-interval-seconds", type=float,
        default=float(os.environ.get("SIMULATION_WORKER_POLL_INTERVAL_SECONDS", "5")),
    )
    parser.add_argument(
        "--lease-seconds", type=int,
        default=int(os.environ.get("SIMULATION_WORKER_LEASE_SECONDS", "300")),
    )
    parser.add_argument(
        "--heartbeat-interval-seconds", type=int,
        default=int(os.environ.get("SIMULATION_WORKER_HEARTBEAT_INTERVAL_SECONDS", "60")),
    )
    parser.add_argument(
        "--resource-profile",
        choices=("quick", "standard", "fine"),
        default=os.environ.get("SIMULATION_WORKER_RESOURCE_PROFILE", "standard"),
        help="数据库算法任务的墙钟预算档位，默认standard。",
    )
    parser.add_argument("--once", action="store_true", help="只领取一次，供部署探针使用。")
    args = parser.parse_args(argv)
    if not args.database_url:
        raise RuntimeError("必须通过--database-url或SIMULATION_DATABASE_URL提供连接串。")
    if args.poll_interval_seconds <= 0:
        raise ValueError("poll-interval-seconds必须大于0。")
    worker_id = args.worker_id or f"{socket.gethostname()}-{os.getpid()}"
    stopping = False

    def request_stop(_signal_number: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    connection = connect_postgres(args.database_url)
    try:
        repository = SimulationRepository(connection)
        while not stopping:
            result = run_one_pending(
                repository,
                worker_id,
                lease_seconds=args.lease_seconds,
                heartbeat_interval_s=args.heartbeat_interval_seconds,
                resource_profile=args.resource_profile,
            )
            print(json.dumps(result or {"status": "idle"}, ensure_ascii=False, default=str), flush=True)
            if args.once:
                break
            if result is None:
                time.sleep(args.poll_interval_seconds)
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
