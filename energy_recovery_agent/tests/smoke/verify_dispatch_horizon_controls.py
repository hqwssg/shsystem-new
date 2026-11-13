# 模块功能说明：验证统一入口把扩展规模实验的时域和搜索间隔参数完整传给调度程序。

from pathlib import Path
from unittest.mock import patch
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import run_project


def _value_after(argv: list[str], option: str) -> str:
    """读取命令参数中指定选项后面的值。"""

    index = argv.index(option)
    return argv[index + 1]


def main() -> int:
    """执行调度时域与搜索边界透传回归。"""

    args = run_project.build_parser().parse_args(
        [
            "dispatch-case",
            "--horizon-s", "25200",
            "--execute-window-s", "2400",
            "--search-min-headway-s", "1500",
            "--search-max-headway-s", "3600",
        ]
    )
    with patch("run_dispatch_case.main", return_value=0) as dispatch_main:
        assert args.func(args) == 0
    forwarded = dispatch_main.call_args.args[0]
    assert _value_after(forwarded, "--horizon-s") == "25200"
    assert _value_after(forwarded, "--execute-window-s") == "2400"
    assert _value_after(forwarded, "--search-min-headway-s") == "1500"
    assert _value_after(forwarded, "--search-max-headway-s") == "3600"
    print("dispatch horizon and headway controls: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
