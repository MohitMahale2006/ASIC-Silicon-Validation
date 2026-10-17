"""Create a Markdown summary from recorded FIFO validation JSON reports."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
SUMMARY_PATH = REPORTS_DIR / "validation_summary.md"
REPORT_FIELDS = {
    "timestamp",
    "random_seed",
    "random_cycle_count",
    "compilation_status",
    "simulation_status",
    "exit_code",
    "elapsed_time_seconds",
}


def classify_report(data: dict[str, Any]) -> str:
    """Classify only explicit outcomes; missing evidence is never a pass."""
    compilation = data.get("compilation_status")
    simulation = data.get("simulation_status")
    exit_code = data.get("exit_code")

    if compilation == "failed" or simulation == "failed":
        return "FAIL"
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        return "FAIL"
    if (
        compilation == "success"
        and simulation == "success"
        and isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code == 0
    ):
        return "PASS"
    return "INCOMPLETE"


def load_reports(reports_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Load validation JSON files and collect parse errors without aborting."""
    reports: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []

    for path in sorted(Path(reports_dir).glob("validation_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            parse_errors.append({"file": path.name, "error": str(error)})
            continue

        if not isinstance(data, dict):
            parse_errors.append(
                {"file": path.name, "error": "expected a JSON object"}
            )
            continue

        reports.append(
            {
                "file": path.name,
                "data": data,
                "status": classify_report(data),
            }
        )

    return reports, parse_errors


def _display(value: Any, *, seconds: bool = False) -> str:
    if value is None:
        return "Not recorded"
    if seconds and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.3f} s"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(
    reports: list[dict[str, Any]],
    parse_errors: list[dict[str, str]],
    generated_at: str | None = None,
) -> str:
    """Render the collected results without inferring missing values."""
    timestamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# FIFO Validation Summary",
        "",
        f"Generated at: {timestamp}",
        "",
        "PASS requires successful compilation, successful simulation, and exit code 0. "
        "Missing or unrecognized result fields are INCOMPLETE, not PASS.",
        "",
    ]

    usable_reports = [
        report
        for report in reports
        if REPORT_FIELDS.intersection(report["data"].keys())
    ]
    if reports:
        lines.extend(
            [
                "| Report | Result | Timestamp | Seed | Random cycles | Compile | Simulation | Exit code | Elapsed |",
                "| --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: |",
            ]
        )
        for report in reports:
            data = report["data"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{report['file']}`",
                        report["status"],
                        _display(data.get("timestamp")),
                        _display(data.get("random_seed")),
                        _display(data.get("random_cycle_count")),
                        _display(data.get("compilation_status")),
                        _display(data.get("simulation_status")),
                        _display(data.get("exit_code")),
                        _display(data.get("elapsed_time_seconds"), seconds=True),
                    ]
                )
                + " |"
            )
    else:
        lines.append("No parseable validation report objects were found.")

    lines.append("")
    if not usable_reports:
        lines.append(
            "No usable validation reports were found. Run "
            "`python scripts/run_validation.py` to create a JSON report."
        )
        lines.append("")

    if parse_errors:
        lines.extend(["## Reports That Could Not Be Parsed", ""])
        for error in parse_errors:
            safe_error = error["error"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"- `{error['file']}`: {safe_error}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_summary(
    reports_dir: Path = REPORTS_DIR,
    output_path: Path = SUMMARY_PATH,
) -> bool:
    """Write the Markdown report; return whether any usable JSON report exists."""
    reports, parse_errors = load_reports(reports_dir)
    usable_reports = any(
        REPORT_FIELDS.intersection(report["data"].keys()) for report in reports
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_markdown(reports, parse_errors), encoding="utf-8"
    )
    print(f"Validation summary written to: {output_path}")
    if not usable_reports:
        print(
            "No usable validation reports were found; see the summary for parse errors.",
            file=sys.stderr,
        )
    return usable_reports


def main() -> int:
    return 0 if generate_summary() else 1


if __name__ == "__main__":
    raise SystemExit(main())