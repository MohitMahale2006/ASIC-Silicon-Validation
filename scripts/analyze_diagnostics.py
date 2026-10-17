"""Analyze recorded validation JSON evidence and write a diagnostic report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_OUTPUT = REPORTS_DIR / "diagnostic_analysis.md"
REPORT_PATTERNS = ("validation_*.json", "regression_*.json")
ASSERTION_HINT = re.compile(
    r"\bFAIL test=|\bFATAL:|assert(?:ion)?(?: error| failure| failed)?", re.I
)
TOOL_HINT = re.compile(
    r"missing required simulator tool|compiler exited|compilation failed", re.I
)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_positive_integer(value: Any) -> bool:
    return _is_int(value) and value > 0


def _report_type(path: Path) -> str:
    return "regression" if path.name.startswith("regression_") else "validation"


def _report_messages(data: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    details = data.get("error_details")
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, str) and detail.strip():
                messages.append({"stage": "reported_error", "message": detail.strip()})
            elif isinstance(detail, dict):
                stage = detail.get("stage")
                parts = (detail.get("message"), detail.get("output"))
                text = " ".join(
                    value.strip()
                    for value in parts
                    if isinstance(value, str) and value.strip()
                )
                if text:
                    messages.append(
                        {
                            "stage": stage if isinstance(stage, str) else "reported_error",
                            "message": text,
                        }
                    )

    steps = data.get("steps")
    if isinstance(steps, dict):
        for stage in ("compilation", "simulation"):
            step = steps.get(stage)
            if isinstance(step, dict) and _is_int(step.get("return_code")):
                messages.append(
                    {
                        "stage": stage,
                        "message": f"Recorded {stage} return code: {step['return_code']}",
                    }
                )
    return messages


def _classify(
    data: dict[str, Any], report_type: str
) -> tuple[str, list[str], list[str]]:
    """Classify from explicit fields; return status, hints, and missing evidence."""
    compilation = data.get("compilation_status")
    simulation = data.get("simulation_status")
    exit_code = data.get("exit_code")
    steps = data.get("steps")
    steps = steps if isinstance(steps, dict) else {}
    compile_step = steps.get("compilation")
    simulation_step = steps.get("simulation")
    compile_rc = compile_step.get("return_code") if isinstance(compile_step, dict) else None
    simulation_rc = (
        simulation_step.get("return_code") if isinstance(simulation_step, dict) else None
    )
    messages = _report_messages(data)
    message_text = " ".join(message["message"] for message in messages)

    compile_failed = compilation == "failed" or (_is_int(compile_rc) and compile_rc != 0)
    simulation_failed = simulation == "failed" or (
        _is_int(simulation_rc) and simulation_rc != 0
    )
    exit_failed = _is_int(exit_code) and exit_code != 0
    if compile_failed or simulation_failed or exit_failed:
        categories: list[str] = []
        stages = {message["stage"].lower() for message in messages}
        if (
            compile_failed
            or stages.intersection({"tool_check", "compilation"})
            or TOOL_HINT.search(message_text)
        ):
            categories.append("compilation_or_tool_error")
        if ASSERTION_HINT.search(message_text):
            categories.append("simulation_assertion_or_testbench_failure")
        if simulation_failed and _is_int(simulation_rc) and simulation_rc != 0:
            categories.append("nonzero_simulation_exit")
        elif simulation_failed and "simulation_assertion_or_testbench_failure" not in categories:
            categories.append("simulation_failure_reported")
        if exit_failed and not categories:
            categories.append("nonzero_validation_exit")
        return "FAIL", categories, []

    missing: list[str] = []
    if compilation != "success":
        missing.append("compilation_status=success")
    if simulation != "success":
        missing.append("simulation_status=success")
    if not _is_int(exit_code) or exit_code != 0:
        missing.append("integer exit_code=0")
    if report_type == "regression":
        configuration = data.get("configuration")
        if not isinstance(configuration, dict):
            missing.append("configuration object")
        else:
            if not _valid_positive_integer(configuration.get("FIFO_DEPTH")):
                missing.append("positive integer configuration.FIFO_DEPTH")
            if not _valid_positive_integer(configuration.get("DATA_WIDTH")):
                missing.append("positive integer configuration.DATA_WIDTH")

    error_details = data.get("error_details")
    has_error_details = isinstance(error_details, list) and bool(error_details)
    if not missing and has_error_details:
        return "INCOMPLETE", ["inconsistent_report_evidence"], [
            "error_details are present despite successful statuses and exit code"
        ]
    if missing:
        return "INCOMPLETE", ["incomplete_evidence"], missing
    return "PASS", ["successful_run"], []


def _context(data: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key, label in (
        ("timestamp", "timestamp"),
        ("random_seed", "seed"),
        ("random_cycle_count", "cycles"),
        ("compilation_status", "compilation"),
        ("simulation_status", "simulation"),
        ("exit_code", "exit_code"),
        ("elapsed_time_seconds", "elapsed_seconds"),
    ):
        if key in data:
            context[label] = data[key]
    configuration = data.get("configuration")
    if isinstance(configuration, dict):
        for key, label in (("FIFO_DEPTH", "depth"), ("DATA_WIDTH", "width")):
            if key in configuration:
                context[label] = configuration[key]
    return context


def _cell(value: Any) -> str:
    if value is None:
        return "Not recorded"
    return str(value).replace("|", "\\|").replace("\n", " ")


def load_diagnostics(input_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load validation/regression JSON files, retaining malformed-file evidence."""
    input_dir = Path(input_dir)
    reports: list[dict[str, Any]] = []
    input_errors: list[str] = []
    if not input_dir.is_dir():
        return reports, [f"Input directory does not exist or is not a directory: {input_dir}"]

    paths = sorted({path for pattern in REPORT_PATTERNS for path in input_dir.glob(pattern)})
    for path in paths:
        report_type = _report_type(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            reports.append(
                {
                    "filename": path.name,
                    "report_type": report_type,
                    "status": "INCOMPLETE",
                    "categories": ["malformed_json", "incomplete_evidence"],
                    "context": {},
                    "evidence": [f"Could not parse JSON: {error}"],
                }
            )
            continue
        if not isinstance(data, dict):
            reports.append(
                {
                    "filename": path.name,
                    "report_type": report_type,
                    "status": "INCOMPLETE",
                    "categories": ["malformed_json", "incomplete_evidence"],
                    "context": {},
                    "evidence": ["Top-level JSON value must be an object."],
                }
            )
            continue

        status, categories, missing = _classify(data, report_type)
        messages = _report_messages(data)
        evidence = [message["message"] for message in messages]
        if missing:
            evidence.extend(f"Missing or invalid required evidence: {field}" for field in missing)
        if status == "PASS":
            evidence.append("Compilation and simulation succeeded with exit code 0.")
        if not evidence:
            evidence.append("Recorded status fields indicate a failure; no diagnostic message was recorded.")
        reports.append(
            {
                "filename": path.name,
                "report_type": report_type,
                "status": status,
                "categories": categories,
                "context": _context(data),
                "evidence": evidence,
            }
        )
    return reports, input_errors


def render_report(
    reports: list[dict[str, Any]],
    input_errors: list[str],
    input_dir: Path,
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = {
        status: sum(report["status"] == status for report in reports)
        for status in ("PASS", "FAIL", "INCOMPLETE")
    }
    if counts["FAIL"]:
        overall = "FAIL"
    elif counts["INCOMPLETE"] or input_errors or not reports:
        overall = "INCOMPLETE"
    else:
        overall = "PASS"

    lines = [
        "# Advanced Validation Diagnostic Analysis",
        "",
        f"Generated at: {generated_at}",
        f"Input directory: `{_cell(input_dir)}`",
        f"**Overall status: {overall}**",
        "",
        f"Totals: {counts['PASS']} PASS, {counts['FAIL']} FAIL, "
        f"{counts['INCOMPLETE']} INCOMPLETE.",
        "",
        "Categories are diagnostic hints based on recorded report evidence; they are not "
        "confirmed hardware or silicon root causes.",
        "",
    ]
    if reports:
        lines.extend(
            [
                "| Report | Type | Timestamp / filename | Seed | Cycles | Depth | Width | Compile | Simulation | Exit | Result | Category hints |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | --- | --- |",
            ]
        )
        for report in reports:
            context = report["context"]
            lines.append(
                "| "
                + " | ".join(
                    _cell(value)
                    for value in (
                        report["filename"],
                        report["report_type"],
                        context.get("timestamp", report["filename"]),
                        context.get("seed"),
                        context.get("cycles"),
                        context.get("depth"),
                        context.get("width"),
                        context.get("compilation"),
                        context.get("simulation"),
                        context.get("exit_code"),
                        report["status"],
                        ", ".join(report["categories"]),
                    )
                )
                + " |"
            )
    else:
        lines.append("No validation or regression JSON reports were found.")

    if input_errors or any(report["status"] != "PASS" for report in reports):
        lines.extend(["", "## Diagnostic Evidence", ""])
        lines.extend(f"- **INCOMPLETE input:** {_cell(error)}" for error in input_errors)
        for report in reports:
            if report["status"] == "PASS":
                continue
            categories = ", ".join(report["categories"])
            lines.append(f"- **{report['status']}** `{report['filename']}` ({categories})")
            lines.extend(f"  - {_cell(item)}" for item in report["evidence"])
    return "\n".join(lines).rstrip() + "\n"


def analyze_directory(input_dir: Path, output_path: Path) -> dict[str, Any]:
    reports, input_errors = load_diagnostics(input_dir)
    counts = {
        status: sum(report["status"] == status for report in reports)
        for status in ("PASS", "FAIL", "INCOMPLETE")
    }
    overall = (
        "FAIL"
        if counts["FAIL"]
        else "INCOMPLETE"
        if counts["INCOMPLETE"] or input_errors or not reports
        else "PASS"
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_report(reports, input_errors, Path(input_dir)), encoding="utf-8"
    )
    print(f"Diagnostic analysis written to: {output_path}")
    print(
        f"Overall: {overall}; PASS={counts['PASS']}, FAIL={counts['FAIL']}, "
        f"INCOMPLETE={counts['INCOMPLETE']}"
    )
    return {
        "overall_status": overall,
        "counts": counts,
        "report_count": len(reports),
        "exit_code": 0 if overall == "PASS" else 1,
        "output_path": output_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze validation and regression JSON evidence."
    )
    parser.add_argument("--input-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return analyze_directory(args.input_dir, args.output)["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())