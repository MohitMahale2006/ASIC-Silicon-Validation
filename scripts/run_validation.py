"""Compile and run the synchronous FIFO simulation with Icarus Verilog."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_SEED = 1
DEFAULT_RANDOM_CYCLES = 100


def _uint32(value: str) -> int:
    """Parse a decimal seed accepted by the testbench's 32-bit state."""
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("seed must be a decimal integer") from error
    if not 0 <= parsed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("seed must be between 0 and 4294967295")
    return parsed


def _non_negative_int(value: str) -> int:
    """Parse a non-negative random-cycle count."""
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("random-cycle count must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("random-cycle count cannot be negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile and run the synchronous FIFO validation testbench."
    )
    parser.add_argument(
        "--seed",
        type=_uint32,
        default=DEFAULT_SEED,
        help=f"32-bit decimal random seed (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--random-cycles",
        type=_non_negative_int,
        default=DEFAULT_RANDOM_CYCLES,
        help=f"number of randomized cycles (default: {DEFAULT_RANDOM_CYCLES})",
    )
    return parser


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _reserve_log_path(reports_dir: Path, timestamp_tag: str) -> tuple[str, Path]:
    """Choose a unique artifact stem without replacing existing reports."""
    suffix = 0
    while True:
        stem = f"validation_{timestamp_tag}"
        if suffix:
            stem = f"{stem}_{suffix}"
        log_path = reports_dir / f"{stem}.log"
        json_path = reports_dir / f"{stem}.json"
        image_path = reports_dir / f"{stem}.vvp"
        if not (log_path.exists() or json_path.exists() or image_path.exists()):
            try:
                log_path.touch(exist_ok=False)
                return stem, log_path
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
            "stdout": completed.stdout,
            "stderr": completed.stderr,
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


def _add_command_log(lines: list[str], label: str, result: dict[str, Any]) -> None:
    lines.extend(
        [
            f"=== {label} ===",
            f"COMMAND: {subprocess.list2cmdline(result['command'])}",
            f"RETURN_CODE: {result['return_code']}",
            f"ELAPSED_TIME_SECONDS: {result['elapsed_time_seconds']:.6f}",
            "--- STDOUT ---",
            result["stdout"].rstrip("\n"),
            "--- STDERR ---",
            result["stderr"].rstrip("\n"),
        ]
    )
    if result["launch_error"]:
        lines.append(f"LAUNCH_ERROR: {result['launch_error']}")
    lines.append("")


def _error_detail(stage: str, result: dict[str, Any], message: str) -> dict[str, str]:
    detail = {"stage": stage, "message": message}
    diagnostic = result["stderr"].strip() or result["stdout"].strip()
    if result["launch_error"]:
        diagnostic = result["launch_error"]
    if diagnostic:
        detail["output"] = diagnostic
    return detail


def run_validation(
    seed: int,
    random_cycles: int,
    project_root: Path = PROJECT_ROOT,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    """Run validation and return the exact summary written to the JSON report."""
    started = time.perf_counter()
    project_root = Path(project_root).resolve()
    reports_dir = Path(reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    timestamp_tag = now.strftime("%Y%m%dT%H%M%S%fZ")
    artifact_stem, log_path = _reserve_log_path(reports_dir, timestamp_tag)
    summary_path = reports_dir / f"{artifact_stem}.json"
    image_path = reports_dir / f"{artifact_stem}.vvp"
    image_argument = _relative_path(image_path, project_root)

    simulator_paths = {
        "iverilog": shutil.which("iverilog"),
        "vvp": shutil.which("vvp"),
    }
    simulator_availability = {
        name: path is not None for name, path in simulator_paths.items()
    }
    summary: dict[str, Any] = {
        "timestamp": timestamp,
        "simulator_availability": simulator_availability,
        "simulator_paths": simulator_paths,
        "compilation_status": "not_run",
        "simulation_status": "not_run",
        "random_seed": seed,
        "random_cycle_count": random_cycles,
        "elapsed_time_seconds": 0.0,
        "log_file_path": _relative_path(log_path, project_root),
        "compiled_file_path": _relative_path(image_path, project_root),
        "error_details": [],
        "steps": {},
        "exit_code": 0,
    }
    log_lines = [
        "ASIC FIFO validation run",
        f"TIMESTAMP: {timestamp}",
        f"RANDOM_SEED: {seed}",
        f"RANDOM_CYCLE_COUNT: {random_cycles}",
        f"IVERILOG_AVAILABLE: {simulator_availability['iverilog']}",
        f"VVP_AVAILABLE: {simulator_availability['vvp']}",
        "",
    ]

    missing_tools = [
        name for name, available in simulator_availability.items() if not available
    ]
    if missing_tools:
        summary["error_details"].append(
            {
                "stage": "tool_check",
                "message": "Missing required simulator tool(s): " + ", ".join(missing_tools),
            }
        )
        summary["exit_code"] = 2
        log_lines.append(summary["error_details"][-1]["message"])
    else:
        compile_command = [
            simulator_paths["iverilog"] or "iverilog",
            "-g2012",
            "-s",
            "tb_sync_fifo",
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
        _add_command_log(log_lines, "COMPILATION", compile_result)

        if compile_result["return_code"] != 0:
            summary["compilation_status"] = "failed"
            summary["error_details"].append(
                _error_detail(
                    "compilation",
                    compile_result,
                    "Compilation could not start."
                    if compile_result["return_code"] is None
                    else f"Compilation failed with exit code {compile_result['return_code']}.",
                )
            )
            summary["exit_code"] = 3
        else:
            summary["compilation_status"] = "success"
            simulation_command = [
                simulator_paths["vvp"] or "vvp",
                image_argument,
                f"+SEED={seed}",
                f"+RANDOM_CYCLES={random_cycles}",
            ]
            simulation_result = _run_command(simulation_command, project_root)
            summary["steps"]["simulation"] = {
                key: simulation_result[key]
                for key in ("command", "return_code", "elapsed_time_seconds")
            }
            _add_command_log(log_lines, "SIMULATION", simulation_result)

            if simulation_result["return_code"] == 0:
                summary["simulation_status"] = "success"
            else:
                summary["simulation_status"] = "failed"
                summary["error_details"].append(
                    _error_detail(
                        "simulation",
                        simulation_result,
                        "Simulation could not start."
                        if simulation_result["return_code"] is None
                        else f"Simulation failed with exit code {simulation_result['return_code']}.",
                    )
                )
                summary["exit_code"] = 4

    summary["elapsed_time_seconds"] = time.perf_counter() - started
    summary["summary_file_path"] = _relative_path(summary_path, project_root)
    if summary["error_details"]:
        log_lines.extend(
            ["=== ERRORS ==="]
            + [json.dumps(detail, sort_keys=True) for detail in summary["error_details"]]
        )

    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    with summary_path.open("x", encoding="utf-8", newline="\n") as summary_file:
        json.dump(summary, summary_file, indent=2)
        summary_file.write("\n")

    print(f"Validation summary: {summary['summary_file_path']}")
    print(f"Validation log: {summary['log_file_path']}")
    print(
        "Status: "
        f"compile={summary['compilation_status']}, "
        f"simulation={summary['simulation_status']}"
    )
    for detail in summary["error_details"]:
        print(f"ERROR: {detail['message']}", file=sys.stderr)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_validation(args.seed, args.random_cycles)
    return summary["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())