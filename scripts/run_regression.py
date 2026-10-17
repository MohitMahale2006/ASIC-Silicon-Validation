"""Run the FIFO validation testbench across multiple parameter sets."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_CONFIGURATIONS = ((5, 8), (3, 8), (5, 16), (8, 32), (16, 8))
PASS_MARKER = "PASS ALL FIFO TESTS"
MINIMUM_TEST_DEPTH = 3


def parse_configuration(value: str) -> tuple[int, int]:
    """Parse DEPTHxWIDTH and enforce the testbench's supported bounds."""
    match = re.fullmatch(r"([0-9]+)[xX]([0-9]+)", value)
    if not match:
        raise argparse.ArgumentTypeError(
            "configuration must use DEPTHxWIDTH format, for example 5x8"
        )
    depth, data_width = (int(part) for part in match.groups())
    if depth < MINIMUM_TEST_DEPTH:
        raise argparse.ArgumentTypeError(
            f"FIFO depth must be at least {MINIMUM_TEST_DEPTH} for this testbench"
        )
    if data_width < 1:
        raise argparse.ArgumentTypeError("data width must be a positive integer")
    return depth, data_width


def _uint32(value: str) -> int:
    try:
        seed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("seed must be a decimal integer") from error
    if not 0 <= seed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("seed must be between 0 and 4294967295")
    return seed


def _non_negative_int(value: str) -> int:
    try:
        cycles = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("random-cycle count must be an integer") from error
    if cycles < 0:
        raise argparse.ArgumentTypeError("random-cycle count cannot be negative")
    return cycles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run normal FIFO simulation across parameter configurations."
    )
    parser.add_argument(
        "--config",
        action="append",
        type=parse_configuration,
        dest="configurations",
        help="FIFO DEPTHxWIDTH; repeat to select multiple configurations",
    )
    parser.add_argument("--seed", type=_uint32, default=1)
    parser.add_argument("--random-cycles", type=_non_negative_int, default=100)
    return parser


def _reserve_paths(reports_dir: Path, depth: int, width: int) -> tuple[str, Path, Path, Path]:
    timestamp_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = 0
    while True:
        stem = f"regression_d{depth}_w{width}_{timestamp_tag}"
        if suffix:
            stem = f"{stem}_{suffix}"
        log_path = reports_dir / f"{stem}.log"
        summary_path = reports_dir / f"{stem}.json"
        image_path = reports_dir / f"{stem}.vvp"
        if not (log_path.exists() or summary_path.exists() or image_path.exists()):
            try:
                log_path.touch(exist_ok=False)
                return stem, log_path, summary_path, image_path
            except FileExistsError:
                pass
        suffix += 1


def _run_command(command: list[str], project_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "command": command,
            "return_code": completed.returncode,
            "elapsed_time_seconds": time.perf_counter() - started,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "launch_error": None,
        }
    except OSError as error:
        return {
            "command": command,
            "return_code": None,
            "elapsed_time_seconds": time.perf_counter() - started,
            "stdout": "",
            "stderr": "",
            "launch_error": str(error),
        }


def _append_step(lines: list[str], name: str, result: dict[str, Any]) -> None:
    lines.extend(
        [
            f"=== {name} ===",
            f"COMMAND: {subprocess.list2cmdline(result['command'])}",
            f"RETURN_CODE: {result['return_code']}",
            f"ELAPSED_TIME_SECONDS: {result['elapsed_time_seconds']:.6f}",
            "--- STDOUT ---",
            result["stdout"].rstrip(),
            "--- STDERR ---",
            result["stderr"].rstrip(),
        ]
    )
    if result["launch_error"]:
        lines.append(f"LAUNCH_ERROR: {result['launch_error']}")
    lines.append("")


def run_configuration(
    depth: int,
    data_width: int,
    seed: int,
    random_cycles: int,
    project_root: Path = PROJECT_ROOT,
    reports_dir: Path = REPORTS_DIR,
    simulator_paths: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Compile and run one configuration, then write its own JSON and log."""
    if depth < MINIMUM_TEST_DEPTH or data_width < 1:
        raise ValueError(
            f"unsupported configuration {depth}x{data_width}; "
            f"depth must be >= {MINIMUM_TEST_DEPTH} and width must be positive"
        )

    project_root = Path(project_root).resolve()
    reports_dir = Path(reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    _, log_path, summary_path, image_path = _reserve_paths(reports_dir, depth, data_width)
    image_argument = image_path.relative_to(project_root).as_posix()
    tools = simulator_paths or {
        "iverilog": shutil.which("iverilog"),
        "vvp": shutil.which("vvp"),
    }

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    summary: dict[str, Any] = {
        "timestamp": timestamp,
        "configuration": {"FIFO_DEPTH": depth, "DATA_WIDTH": data_width},
        "random_seed": seed,
        "random_cycle_count": random_cycles,
        "simulator_paths": tools,
        "compilation_status": "not_run",
        "simulation_status": "not_run",
        "elapsed_time_seconds": 0.0,
        "log_file_path": log_path.relative_to(project_root).as_posix(),
        "compiled_file_path": image_argument,
        "error_details": [],
        "steps": {},
        "exit_code": 0,
    }
    log_lines = [
        "ASIC FIFO parameter regression",
        f"TIMESTAMP: {timestamp}",
        f"FIFO_DEPTH: {depth}",
        f"DATA_WIDTH: {data_width}",
        f"RANDOM_SEED: {seed}",
        f"RANDOM_CYCLE_COUNT: {random_cycles}",
        f"IVERILOG_AVAILABLE: {tools['iverilog'] is not None}",
        f"VVP_AVAILABLE: {tools['vvp'] is not None}",
        "",
    ]
    started = time.perf_counter()

    missing_tools = [name for name in ("iverilog", "vvp") if not tools.get(name)]
    if missing_tools:
        summary["exit_code"] = 2
        summary["error_details"].append(
            "Missing required simulator tool(s): " + ", ".join(missing_tools)
        )
    else:
        compile_command = [
            tools["iverilog"],
            "-g2012",
            "-s",
            "tb_sync_fifo",
            "-P",
            f"tb_sync_fifo.FIFO_DEPTH={depth}",
            "-P",
            f"tb_sync_fifo.DATA_WIDTH={data_width}",
            "-o",
            image_argument,
            "rtl/sync_fifo.sv",
            "tb/tb_sync_fifo.sv",
        ]
        compile_result = _run_command(compile_command, project_root)
        summary["steps"]["compilation"] = {
            key: compile_result[key]
            for key in ("command", "return_code", "elapsed_time_seconds")
        }
        _append_step(log_lines, "COMPILATION", compile_result)

        if compile_result["return_code"] != 0:
            summary["compilation_status"] = "failed"
            summary["exit_code"] = 3
            summary["error_details"].append(
                compile_result["launch_error"]
                or compile_result["stderr"]
                or compile_result["stdout"]
                or f"Compiler exited with {compile_result['return_code']}"
            )
        else:
            summary["compilation_status"] = "success"
            simulation_command = [
                tools["vvp"],
                image_argument,
                f"+SEED={seed}",
                f"+RANDOM_CYCLES={random_cycles}",
            ]
            simulation_result = _run_command(simulation_command, project_root)
            simulation_output = simulation_result["stdout"] + simulation_result["stderr"]
            summary["steps"]["simulation"] = {
                key: simulation_result[key]
                for key in ("command", "return_code", "elapsed_time_seconds")
            }
            _append_step(log_lines, "SIMULATION", simulation_result)
            passed = (
                simulation_result["return_code"] == 0
                and PASS_MARKER in simulation_output
            )
            summary["simulation_status"] = "success" if passed else "failed"
            if not passed:
                summary["exit_code"] = 4
                summary["error_details"].append(
                    simulation_result["launch_error"]
                    or simulation_result["stderr"]
                    or (
                        f"Simulation exited with {simulation_result['return_code']}"
                        if simulation_result["return_code"] != 0
                        else f"Simulation output did not contain {PASS_MARKER!r}"
                    )
                )

    summary["elapsed_time_seconds"] = time.perf_counter() - started
    summary["summary_file_path"] = summary_path.relative_to(project_root).as_posix()
    log_lines.extend(
        [
            f"COMPILATION_STATUS: {summary['compilation_status']}",
            f"SIMULATION_STATUS: {summary['simulation_status']}",
            f"CONFIGURATION_EXIT_CODE: {summary['exit_code']}",
            f"ELAPSED_TIME_SECONDS: {summary['elapsed_time_seconds']:.6f}",
        ]
    )
    if summary["error_details"]:
        log_lines.extend(["ERRORS:", *summary["error_details"]])
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    with summary_path.open("x", encoding="utf-8", newline="\n") as summary_file:
        json.dump(summary, summary_file, indent=2)
        summary_file.write("\n")
    return summary


def run_regression(
    configurations: tuple[tuple[int, int], ...] = DEFAULT_CONFIGURATIONS,
    seed: int = 1,
    random_cycles: int = 100,
    project_root: Path = PROJECT_ROOT,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    """Run every requested config and return a nonzero aggregate on any failure."""
    if not configurations:
        raise ValueError("at least one FIFO configuration is required")
    if len(set(configurations)) != len(configurations):
        raise ValueError("duplicate FIFO configurations are not allowed")

    tools = {"iverilog": shutil.which("iverilog"), "vvp": shutil.which("vvp")}
    results = [
        run_configuration(
            depth,
            width,
            seed,
            random_cycles,
            project_root,
            reports_dir,
            tools,
        )
        for depth, width in configurations
    ]
    passed = all(
        result["compilation_status"] == "success"
        and result["simulation_status"] == "success"
        and result["exit_code"] == 0
        for result in results
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "exit_code": 0 if passed else 1,
        "configurations": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configurations = tuple(args.configurations or DEFAULT_CONFIGURATIONS)
    if len(set(configurations)) != len(configurations):
        parser.error("duplicate --config values are not allowed")

    try:
        result = run_regression(configurations, args.seed, args.random_cycles)
    except ValueError as error:
        parser.error(str(error))

    for item in result["configurations"]:
        depth = item["configuration"]["FIFO_DEPTH"]
        width = item["configuration"]["DATA_WIDTH"]
        print(
            f"CONFIG {depth}x{width}: {item['compilation_status']} compile, "
            f"{item['simulation_status']} simulation, exit={item['exit_code']}"
        )
        print(f"  Summary: {item['summary_file_path']}")
        print(f"  Log: {item['log_file_path']}")
    print(f"Regression: {result['status']}")
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())