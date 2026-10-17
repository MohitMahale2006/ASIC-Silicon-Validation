"""Generate a Markdown matrix from per-configuration regression JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
SUMMARY_PATH = REPORTS_DIR / "regression_matrix.md"


def _valid_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def classify_configuration(data: dict[str, Any]) -> str:
    """Classify recorded outcomes without promoting missing fields to PASS."""
    compilation = data.get("compilation_status")
    simulation = data.get("simulation_status")
    exit_code = data.get("exit_code")

    if compilation == "failed" or simulation == "failed":
        return "FAIL"
    if (
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code != 0
    ):
        return "FAIL"

    configuration = data.get("configuration")
    if not isinstance(configuration, dict):
        return "INCOMPLETE"
    if not (
        _valid_positive_integer(configuration.get("FIFO_DEPTH"))
        and _valid_positive_integer(configuration.get("DATA_WIDTH"))
        and compilation == "success"
        and simulation == "success"
        and isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code == 0
    ):
        return "INCOMPLETE"
    return "PASS"


def load_regression_reports(
    reports_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Read per-configuration JSON reports and retain parse errors by filename."""
    records: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []

    for path in sorted(Path(reports_dir).glob("regression_*.json")):
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

        records.append(
            {
                "file": path.name,
                "data": data,
                "status": classify_configuration(data),
            }
        )
    return records, parse_errors


def _display(value: Any) -> str:
    if value is None:
        return "Not recorded"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_matrix(
    records: list[dict[str, Any]],
    parse_errors: list[dict[str, str]],
    generated_at: str | None = None,
) -> str:
    """Render configuration outcomes and parse issues as Markdown."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    totals = {
        status: sum(record["status"] == status for record in records)
        for status in ("PASS", "FAIL", "INCOMPLETE")
    }
    if totals["FAIL"]:
        overall = "FAIL"
    elif totals["INCOMPLETE"] or parse_errors or not records:
        overall = "INCOMPLETE"
    else:
        overall = "PASS"

    lines = [
        "# FIFO Regression Matrix",
        "",
        f"Generated at: {generated_at}",
        "",
        f"**Overall regression status: {overall}**",
        "",
        f"Totals: {totals['PASS']} passed, {totals['FAIL']} failed, "
        f"{totals['INCOMPLETE']} incomplete configuration(s).",
        "",
        "A configuration is PASS only when both stages report `success`, "
        "the exit code is integer `0`, and both parameter values are present. "
        "Malformed JSON files are listed separately and are not counted as configurations.",
        "",
    ]

    if records:
        lines.extend(
            [
                "| Report | FIFO depth | Data width | Compilation | Simulation | Exit code | Result |",
                "| --- | ---: | ---: | --- | --- | ---: | --- |",
            ]
        )
        for record in records:
            data = record["data"]
            configuration = data.get("configuration")
            if not isinstance(configuration, dict):
                configuration = {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{record['file']}`",
                        _display(configuration.get("FIFO_DEPTH")),
                        _display(configuration.get("DATA_WIDTH")),
                        _display(data.get("compilation_status")),
                        _display(data.get("simulation_status")),
                        _display(data.get("exit_code")),
                        record["status"],
                    ]
                )
                + " |"
            )
    else:
        lines.append(
            "No usable regression JSON reports were found. Run "
            "`python scripts/run_regression.py` to create per-configuration reports."
        )

    if parse_errors:
        lines.extend(["", "## Malformed or Unreadable Reports", ""])
        for error in parse_errors:
            safe_error = error["error"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"- `{error['file']}`: {safe_error}")
    elif not records:
        lines.extend(["", "No regression configurations could be summarized."])

    return "\n".join(lines).rstrip() + "\n"


def generate_matrix(
    reports_dir: Path = REPORTS_DIR,
    output_path: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    """Write the matrix report and return its actual summary counts/status."""
    records, parse_errors = load_regression_reports(reports_dir)
    totals = {
        status: sum(record["status"] == status for record in records)
        for status in ("PASS", "FAIL", "INCOMPLETE")
    }
    overall = (
        "FAIL"
        if totals["FAIL"]
        else "INCOMPLETE"
        if totals["INCOMPLETE"] or parse_errors or not records
        else "PASS"
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_matrix(records, parse_errors), encoding="utf-8"
    )

    result = {
        "overall_status": overall,
        "totals": totals,
        "report_count": len(records),
        "malformed_report_count": len(parse_errors),
        "exit_code": 0 if overall == "PASS" else 1,
        "output_path": output_path,
    }
    print(f"Regression matrix written to: {output_path}")
    print(
        f"Overall: {overall}; passed={totals['PASS']}, failed={totals['FAIL']}, "
        f"incomplete={totals['INCOMPLETE']}, malformed={len(parse_errors)}"
    )
    if not records:
        print("No usable regression reports were found.", file=sys.stderr)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize per-configuration FIFO regression JSON reports."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=REPORTS_DIR,
        help=f"directory containing regression_*.json reports (default: {REPORTS_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SUMMARY_PATH,
        help=f"Markdown output path (default: {SUMMARY_PATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return generate_matrix(args.input_dir, args.output)["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())