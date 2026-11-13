"""运行项目代码质量门禁并输出可复核的静态质量报告。"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tokenize
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT, ROOT / "database", ROOT / "tools")
EXCLUDED_PARTS = {"deliverables", "outputs", ".venv", "__pycache__"}
CRITICAL_TESTS = (
    "tests/smoke/verify_energy_settlement_correctness.py",
    "tests/smoke/verify_rolling_commit_gate.py",
    "tests/smoke/verify_rolling_storage_device_state.py",
    "tests/smoke/verify_robustness_contracts.py",
)


def _source_files() -> list[Path]:
    """返回当前工作区中需要静态检查的项目源码文件。"""

    files: set[Path] = set()
    for source_root in SOURCE_ROOTS:
        if not source_root.exists():
            continue
        for path in source_root.rglob("*.py"):
            relative_parts = set(path.relative_to(ROOT).parts)
            if relative_parts & EXCLUDED_PARTS:
                continue
            if path.parts[-2:] == ("tests", "__init__.py"):
                continue
            files.add(path)
    return sorted(files)


def _complexity(node: ast.AST) -> int:
    """计算函数的轻量分支复杂度，用于定位需要人工复核的热点。"""

    branches = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.IfExp, ast.BoolOp, ast.comprehension)
    return 1 + sum(isinstance(child, branches) for child in ast.walk(node))


def _analyze(path: Path) -> dict[str, object]:
    """解析单个源码文件并收集结构指标与硬错误。"""

    relative = path.relative_to(ROOT).as_posix()
    result: dict[str, object] = {
        "path": relative,
        "syntax_ok": True,
        "line_count": len(path.read_text(encoding="utf-8").splitlines()),
        "function_count": 0,
        "annotated_function_count": 0,
        "docstring_function_count": 0,
        "high_complexity_functions": [],
        "bare_except_lines": [],
        "todo_lines": [],
        "parse_error": None,
    }
    try:
        with tokenize.open(path) as stream:
            ast_root = ast.parse(stream.read(), filename=relative)
    except (SyntaxError, UnicodeError, OSError) as exc:
        result["syntax_ok"] = False
        result["parse_error"] = f"{type(exc).__name__}: {exc}"
        return result

    functions = [node for node in ast.walk(ast_root) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    result["function_count"] = len(functions)
    annotated = 0
    documented = 0
    high_complexity: list[dict[str, object]] = []
    for function in functions:
        arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        has_annotation = function.returns is not None or any(argument.annotation is not None for argument in arguments)
        annotated += int(has_annotation)
        documented += int(ast.get_docstring(function) is not None)
        complexity = _complexity(function)
        if complexity > 25:
            high_complexity.append({"name": function.name, "line": function.lineno, "complexity": complexity})
    result["annotated_function_count"] = annotated
    result["docstring_function_count"] = documented
    result["high_complexity_functions"] = high_complexity
    result["bare_except_lines"] = [node.lineno for node in ast.walk(ast_root) if isinstance(node, ast.ExceptHandler) and node.type is None]
    result["todo_lines"] = []
    try:
        with tokenize.open(path) as stream:
            for token in tokenize.generate_tokens(stream.readline):
                if token.type == tokenize.COMMENT and any(
                    marker in token.string.upper() for marker in ("TODO", "FIXME")
                ):
                    result["todo_lines"].append(token.start[0])
    except tokenize.TokenError:
        # 语法错误已经由 AST 解析结果单独报告，此处不重复制造指标。
        result["todo_lines"] = []
    return result


def _run_critical_tests(output_dir: Path) -> list[dict[str, object]]:
    """运行关键业务路径的快速回归测试。"""

    results: list[dict[str, object]] = []
    for relative in CRITICAL_TESTS:
        command = [sys.executable, relative]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        (output_dir / (Path(relative).stem + ".stdout.txt")).write_text(completed.stdout, encoding="utf-8")
        (output_dir / (Path(relative).stem + ".stderr.txt")).write_text(completed.stderr, encoding="utf-8")
        results.append({"test": relative, "return_code": completed.returncode, "passed": completed.returncode == 0})
    return results


def main() -> int:
    """执行代码结构分析和关键路径回归。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/code_quality_gate"))
    parser.add_argument("--skip-critical-tests", action="store_true", help="只执行静态分析")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    files = [_analyze(path) for path in _source_files()]
    hard_failures = [
        {"path": row["path"], "reason": row["parse_error"]}
        for row in files
        if not row["syntax_ok"]
    ]
    warnings = [
        {"path": row["path"], "kind": "bare_except", "lines": row["bare_except_lines"]}
        for row in files
        if row["bare_except_lines"]
    ]
    warnings.extend(
        {"path": row["path"], "kind": "todo_or_fixme", "lines": row["todo_lines"]}
        for row in files
        if row["todo_lines"]
    )
    total_functions = sum(int(row["function_count"]) for row in files)
    annotated_functions = sum(int(row["annotated_function_count"]) for row in files)
    documented_functions = sum(int(row["docstring_function_count"]) for row in files)
    critical_tests = [] if args.skip_critical_tests else _run_critical_tests(output_dir)
    test_failures = [row for row in critical_tests if not row["passed"]]
    summary = {
        "schema_version": "1.0",
        "scope": "工作区源码（排除交付包、输出物和缓存）",
        "source_file_count": len(files),
        "syntax_error_count": len(hard_failures),
        "function_count": total_functions,
        "annotated_function_count": annotated_functions,
        "annotation_rate": round(annotated_functions / total_functions, 4) if total_functions else 0.0,
        "documented_function_count": documented_functions,
        "docstring_rate": round(documented_functions / total_functions, 4) if total_functions else 0.0,
        "high_complexity_function_count": sum(len(row["high_complexity_functions"]) for row in files),
        "warnings": warnings,
        "hard_failures": hard_failures,
        "critical_tests": critical_tests,
        "critical_test_failure_count": len(test_failures),
        "accepted": not hard_failures and not test_failures,
        "quality_boundary": {
            "hard_gate": "语法错误和关键业务回归失败",
            "review_metrics": "裸except、TODO/FIXME和复杂度超过25只作为人工复核指标，不自动判失败",
            "not_covered": "运行时类型、第三方漏洞、正式数据正确性、现场性能和目标平台联调",
        },
        "files": files,
    }
    (output_dir / "code_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 代码质量专项报告",
        "",
        f"- 静态源码文件：`{len(files)}`",
        f"- 函数总数：`{total_functions}`；参数或返回值带类型标注：`{annotated_functions}`（{summary['annotation_rate']:.1%}）",
        f"- 有函数文档字符串：`{documented_functions}`（{summary['docstring_rate']:.1%}）",
        f"- 高复杂度函数（>25）：`{summary['high_complexity_function_count']}`，仅需人工复核",
        f"- 关键业务回归：`{len(critical_tests) - len(test_failures)}/{len(critical_tests)}`",
        f"- 门禁结论：`{'PASS' if summary['accepted'] else 'FAIL'}`",
        "",
        "## 质量边界",
        "",
        "硬门禁只拦截语法错误和关键业务回归失败；裸 `except`、TODO/FIXME 和高复杂度函数保留为人工复核指标。第三方依赖安全、正式数据和现场环境不由本专项代替。",
    ]
    complex_rows = [
        item | {"path": row["path"]}
        for row in files
        for item in row["high_complexity_functions"]
    ]
    if complex_rows:
        lines.extend(["", "## 高复杂度函数（人工复核）", "", "| 文件 | 函数 | 行号 | 复杂度 |", "| --- | --- | ---: | ---: |"])
        lines.extend(
            f"| `{item['path']}` | `{item['name']}` | {item['line']} | {item['complexity']} |"
            for item in sorted(complex_rows, key=lambda value: (-int(value["complexity"]), str(value["path"])))[:100]
        )
    if warnings:
        lines.extend(["", "## 人工复核项", "", "| 文件 | 类型 | 行号 |", "| --- | --- | --- |"])
        lines.extend(f"| `{row['path']}` | `{row['kind']}` | `{','.join(map(str, row['lines']))}` |" for row in warnings)
    (output_dir / "CODE_QUALITY_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"accepted": summary["accepted"], "report": str(output_dir / "CODE_QUALITY_REPORT.md"), "summary": str(output_dir / "code_quality_summary.json")}, ensure_ascii=False))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
