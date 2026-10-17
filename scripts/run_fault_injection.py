"""Run an isolated, test-only read-data fault against the FIFO testbench."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
RTL_PATH = PROJECT_ROOT / "rtl" / "sync_fifo.sv"
TESTBENCH_PATH = PROJECT_ROOT / "tb" / "tb_sync_fifo.sv"
READ_STATEMENT = "data_out <= storage[read_ptr];"
FAULTY_READ_STATEMENT = (
    "data_out <= storage[read_ptr] ^ {{(DATA_WIDTH-1){1'b0}}, 1'b1};"
)
EXPECTED_DIAGNOSTIC = "FAIL test=single_read_zero cycle=3 seed=1 data_out expected=0x00 actual=0x01"


def inject_read_data_fault(source: str) -> str:
    """Return a test-only source copy with the read-data LSB inverted."""
    if source.count(READ_STATEMENT) != 1:
        raise ValueError("Expected exactly one FIFO read-data assignment to mutate")
    return source.replace(READ_STATEMENT, FAULTY_READ_STATEMENT, 1)


def classify_fault_result(
    compile_return_code: int | None,
    simulation_return_code: int | None,
    simulation_output: str,
) -> str:
    """Separate a detected injected fault from build/tool and unrelated failures."""
    if compile_return_code is None or compile_return_code != 0:
        return "compile_error"
    if simulation_return_code is None:
        return "simulation_error"
    if simulation_return_code == 0:
        return "fault_not_detected"
    if EXPECTED_DIAGNOSTIC in simulation_output:
        return "fault_detected"
    return "unexpected_simulation_failure"


def _reserve_artifact_stem(reports_dir: Path, timestamp_tag: str) -> str:
    suffix = 0
    while True:
        stem = f"fault_injection_{timestamp_tag}"
        if suffix:
            stem = f"{stem}_{suffix}"
        paths = [reports_dir / f"{stem}.{extension}" for extension in ("log", "json", "vvp")]
        if not any(path.exists() for path in paths):
            try:
                paths[0].touch(exist_ok=False)
                return stem
            except FileExistsError:
                pass
        suffix += 1


def _run_command(command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
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


def run_fault_injection() -> dict[str, Any]:
    """Compile and execute the temporary faulty RTL, saving artifacts in reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    stem = _reserve_artifact_stem(REPORTS_DIR, now.strftime("%Y%m%dT%H%M%S%fZ"))
    log_path = REPORTS_DIR / f"{stem}.log"
    summary_path = REPORTS_DIR / f"{stem}.json"
    image_path = REPORTS_DIR / f"{stem}.vvp"
    image_argument = image_path.relative_to(PROJECT_ROOT).as_posix()

    tools = {name: shutil.which(name) for name in ("iverilog", "vvp")}
    summary: dict[str, Any] = {
        "timestamp": timestamp,
        "fault": "invert the least-significant bit of each accepted read value",
        "expected_diagnostic": EXPECTED_DIAGNOSTIC,
        "compilation_status": "not_run",
        "simulation_status": "not_run",
        "simulation_return_code": None,
        "detection_status": "not_run",
        "elapsed_time_seconds": 0.0,
        "log_file_path": log_path.relative_to(PROJECT_ROOT).as_posix(),
        "compiled_file_path": image_argument,
        "tool_paths": tools,
        "error_details": [],
        "steps": {},
        "exit_code": 2,
    }
    lines = [
        "ASIC FIFO fault-injection run",
        f"TIMESTAMP: {timestamp}",
        f"FAULT: {summary['fault']}",
        f"EXPECTED_DIAGNOSTIC: {EXPECTED_DIAGNOSTIC}",
        f"IVERILOG_AVAILABLE: {tools['iverilog'] is not None}",
        f"VVP_AVAILABLE: {tools['vvp'] is not None}",
        "",
    ]

    missing_tools = [name for name, path in tools.items() if path is None]
    if missing_tools:
        summary["detection_status"] = "tool_error"
        summary["error_details"].append(
            "Missing required simulator tool(s): " + ", ".join(missing_tools)
        )
    else:
        source_text = RTL_PATH.read_text(encoding="utf-8")
        try:
            faulty_source = inject_read_data_fault(source_text)
        except ValueError as error:
            summary["detection_status"] = "fault_setup_error"
            summary["error_details"].append(str(error))
        else:
            with tempfile.TemporaryDirectory(prefix="fifo_fault_injection_") as temp_dir:
                faulty_rtl_path = Path(temp_dir) / "sync_fifo_faulty.sv"
                faulty_rtl_path.write_text(faulty_source, encoding="utf-8")
                compile_result = _run_command(
                    [
                        tools["iverilog"],
                        "-g2012",
                        "-s",
                        "tb_sync_fifo",
                        "-o",
                        image_argument,
                        str(faulty_rtl_path),
                        TESTBENCH_PATH.relative_to(PROJECT_ROOT).as_posix(),
                    ]
                )
                summary["steps"]["compilation"] = {
                    key: compile_result[key]
                    for key in ("command", "return_code", "elapsed_time_seconds")
                }
                _append_step(lines, "COMPILATION", compile_result)

                if compile_result["return_code"] != 0:
                    summary["compilation_status"] = "failed"
                    summary["detection_status"] = "compile_error"
                    summary["error_details"].append(
                        compile_result["launch_error"]
                        or compile_result["stderr"]
                        or compile_result["stdout"]
                        or f"Compiler exited with {compile_result['return_code']}"
                    )
                else:
                    summary["compilation_status"] = "success"
                    simulation_result = _run_command(
                        [
                            tools["vvp"],
                            image_argument,
                            "+SEED=1",
                            "+RANDOM_CYCLES=0",
                        ]
                    )
                    simulation_output = (
                        simulation_result["stdout"] + simulation_result["stderr"]
                    )
                    summary["simulation_return_code"] = simulation_result["return_code"]
                    summary["simulation_status"] = (
                        "failed"
                        if simulation_result["return_code"] not in (None, 0)
                        else "success"
                        if simulation_result["return_code"] == 0
                        else "not_run"
                    )
                    summary["steps"]["simulation"] = {
                        key: simulation_result[key]
                        for key in ("command", "return_code", "elapsed_time_seconds")
                    }
                    _append_step(lines, "SIMULATION", simulation_result)
                    summary["detection_status"] = classify_fault_result(
                        compile_result["return_code"],
                        simulation_result["return_code"],
                        simulation_output,
                    )
                    if summary["detection_status"] == "fault_detected":
                        summary["exit_code"] = 0
                    else:
                        summary["exit_code"] = 1
                        summary["error_details"].append(
                            "Injected fault was not confirmed: "
                            + summary["detection_status"]
                        )

    summary["elapsed_time_seconds"] = time.perf_counter() - started
    summary["summary_file_path"] = summary_path.relative_to(PROJECT_ROOT).as_posix()
    lines.extend(
        [
            f"DETECTION_STATUS: {summary['detection_status']}",
            f"FAULT_INJECTION_EXIT_CODE: {summary['exit_code']}",
        ]
    )
    if summary["error_details"]:
        lines.extend(["ERRORS:", *summary["error_details"]])
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with summary_path.open("x", encoding="utf-8", newline="\n") as summary_file:
        json.dump(summary, summary_file, indent=2)
        summary_file.write("\n")

    print(f"Fault-injection summary: {summary['summary_file_path']}")
    print(f"Fault-injection log: {summary['log_file_path']}")
    print(f"Detection status: {summary['detection_status']}")
    print(f"Simulation return code: {summary['simulation_return_code']}")
    for error in summary["error_details"]:
        print(f"ERROR: {error}", file=sys.stderr)
    return summary


def main() -> int:
    return run_fault_injection()["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())