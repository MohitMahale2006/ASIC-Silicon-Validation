"""Parse SV JSONL traces, compare against the Python model, and summarize hits."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from verification.fifo_reference_model import SynchronousFifoModel


TRACE_PREFIX = "TRACE_JSON "
PASS_LINE = re.compile(r"^PASS test=(\w+) cycle=(\d+) (.*)$")
FINAL_PASS = re.compile(r"PASS ALL FIFO TESTS cycles=(\d+) seed=(\d+)")
SCENARIOS = (
    ("fifo_reached_full", "FIFO reached full with status asserted."),
    ("fifo_reached_empty", "FIFO drained to empty with status asserted."),
    ("simultaneous_read_write", "Read and write were both accepted while partially occupied."),
    ("read_pointer_wraparound", "Read pointer advanced through its wraparound test."),
    ("write_pointer_wraparound", "Write pointer advanced through its wraparound test."),
    ("read_rejected_while_empty", "Read request at empty was rejected without changing state."),
    ("write_rejected_while_full", "Write request at full was rejected without changing state."),
    ("reset_while_populated", "Synchronous reset cleared a populated FIFO."),
)

TRACE_KEYS = {
    "cycle", "test", "rst_n", "wr_en", "rd_en", "data_in_hex",
    "data_out_hex", "occupancy", "full", "empty",
}


def parse_trace_lines(simulator_output: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse TRACE_JSON records; unrelated simulator output is ignored."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(simulator_output.splitlines(), start=1):
        if not line.startswith(TRACE_PREFIX):
            continue
        try:
            record = json.loads(line[len(TRACE_PREFIX) :])
        except json.JSONDecodeError as error:
            errors.append(f"line {line_number}: malformed TRACE_JSON: {error}")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_number}: trace record must be a JSON object")
            continue
        missing = TRACE_KEYS - record.keys()
        if missing:
            errors.append(
                f"line {line_number}: missing trace fields: {', '.join(sorted(missing))}"
            )
            continue
        integer_fields = (
            "cycle", "rst_n", "wr_en", "rd_en", "occupancy", "full", "empty"
        )
        if any(
            not isinstance(record[field], int) or isinstance(record[field], bool)
            for field in integer_fields
        ):
            errors.append(f"line {line_number}: trace control/state fields must be integers")
            continue
        if (
            not isinstance(record["test"], str)
            or not isinstance(record["data_in_hex"], str)
            or not isinstance(record["data_out_hex"], str)
        ):
            errors.append(f"line {line_number}: test/data trace fields must be strings")
            continue
        if any(
            record[field] not in (0, 1)
            for field in ("rst_n", "wr_en", "rd_en", "full", "empty")
        ):
            errors.append(f"line {line_number}: trace bit fields must be 0 or 1")
            continue
        try:
            int(record["data_in_hex"], 16)
            int(record["data_out_hex"], 16)
        except ValueError:
            errors.append(f"line {line_number}: data trace fields must be hexadecimal")
            continue
        records.append(record)
    return records, errors


def compare_trace_to_model(
    simulator_output: str, depth: int, data_width: int
) -> dict[str, Any]:
    """Replay the SV-recorded inputs and compare post-edge observable outputs."""
    records, errors = parse_trace_lines(simulator_output)
    model = SynchronousFifoModel(depth=depth, data_width=data_width)
    mismatches: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        if record["cycle"] != index:
            errors.append(
                f"trace cycle sequence expected {index}, got {record['cycle']}"
            )
        expected = model.step(
            rst_n=bool(record["rst_n"]),
            wr_en=bool(record["wr_en"]),
            rd_en=bool(record["rd_en"]),
            data_in=int(record["data_in_hex"], 16),
        )
        actual_values = {
            "data_out": int(record["data_out_hex"], 16),
            "occupancy": record["occupancy"],
            "full": bool(record["full"]),
            "empty": bool(record["empty"]),
        }
        for field, actual in actual_values.items():
            if expected[field] != actual:
                mismatches.append(
                    {
                        "cycle": record["cycle"],
                        "test": record["test"],
                        "field": field,
                        "expected": expected[field],
                        "actual": actual,
                    }
                )

    final_pass = FINAL_PASS.search(simulator_output)
    if not records:
        errors.append("no TRACE_JSON records were found")
    if final_pass is None:
        errors.append("testbench final PASS marker was not found")
    elif int(final_pass.group(1)) != len(records):
        errors.append(
            f"final PASS cycle count {final_pass.group(1)} does not match "
            f"{len(records)} trace records"
        )

    status = "mismatch" if mismatches else "incomplete" if errors else "match"
    return {
        "status": status,
        "trace_records": len(records),
        "mismatches": mismatches,
        "errors": errors,
    }


def collect_scenario_coverage(simulator_output: str, depth: int) -> dict[str, Any]:
    """Count scenarios only when a passing SV check and its trace support the hit."""
    events: dict[int, tuple[str, str]] = {}
    for line in simulator_output.splitlines():
        match = PASS_LINE.match(line)
        if match:
            events[int(match.group(2))] = (match.group(1), match.group(3))
    traces, _ = parse_trace_lines(simulator_output)
    trace_by_cycle = {record["cycle"]: record for record in traces}
    previous_by_cycle = {
        record["cycle"]: traces[index - 1] if index > 0 else None
        for index, record in enumerate(traces)
    }
    evidence: dict[str, list[str]] = {name: [] for name, _ in SCENARIOS}
    accepted_read_wrap_test_ops = 0
    accepted_write_wrap_test_ops = 0

    for cycle, (test_name, text) in events.items():
        trace = trace_by_cycle.get(cycle)
        if trace is None:
            continue
        previous = previous_by_cycle[cycle]
        if (
            test_name == "fill_to_full"
            and trace["full"] == 1
            and "full expected=1 actual=1" in text
        ):
            evidence["fifo_reached_full"].append(f"PASS test={test_name} cycle={cycle}")
        if (
            test_name == "drain_after_rejected_write"
            and trace["empty"] == 1
            and "empty expected=1 actual=1" in text
        ):
            evidence["fifo_reached_empty"].append(f"PASS test={test_name} cycle={cycle}")
        if (
            test_name == "simultaneous_partially_occupied"
            and trace["wr_en"] == 1
            and trace["rd_en"] == 1
            and previous is not None
            and 0 < previous["occupancy"] < depth
            and trace["occupancy"] == previous["occupancy"]
        ):
            evidence["simultaneous_read_write"].append(
                f"PASS test={test_name} cycle={cycle}"
            )
        if (
            test_name == "read_pointer_wrap"
            and trace["rd_en"] == 1
            and previous is not None
            and previous["occupancy"] > 0
        ):
            accepted_read_wrap_test_ops += 1
        if (
            test_name == "write_pointer_wrap"
            and trace["wr_en"] == 1
            and previous is not None
            and previous["occupancy"] < depth
        ):
            accepted_write_wrap_test_ops += 1
        if (
            test_name == "read_rejected_when_empty"
            and trace["rd_en"] == 1
            and previous is not None
            and previous["occupancy"] == 0
            and trace["occupancy"] == 0
            and trace["empty"] == 1
        ):
            evidence["read_rejected_while_empty"].append(
                f"PASS test={test_name} cycle={cycle}"
            )
        if (
            test_name == "write_rejected_when_full"
            and trace["wr_en"] == 1
            and previous is not None
            and previous["occupancy"] == depth
            and trace["occupancy"] == depth
            and trace["full"] == 1
        ):
            evidence["write_rejected_while_full"].append(
                f"PASS test={test_name} cycle={cycle}"
            )

    if accepted_read_wrap_test_ops > depth:
        evidence["read_pointer_wraparound"].append(
            f"{accepted_read_wrap_test_ops} accepted reads in a {depth + 2}-iteration wrap test"
        )
    if accepted_write_wrap_test_ops > depth:
        evidence["write_pointer_wraparound"].append(
            f"{accepted_write_wrap_test_ops} accepted writes in a {depth + 2}-iteration wrap test"
        )

    populated_setup = [
        (cycle, trace)
        for cycle, (test_name, _text) in events.items()
        if test_name == "reset_during_operation_setup"
        and (trace := trace_by_cycle.get(cycle)) is not None
        and trace["occupancy"] > 0
    ]
    for reset_cycle, (test_name, _text) in events.items():
        reset_trace = trace_by_cycle.get(reset_cycle)
        if (
            test_name == "reset_during_operation"
            and reset_trace is not None
            and reset_trace["rst_n"] == 0
            and reset_trace["occupancy"] == 0
            and reset_trace["empty"] == 1
            and any(setup_cycle < reset_cycle for setup_cycle, _ in populated_setup)
        ):
            evidence["reset_while_populated"].append(
                f"populated setup before PASS test={test_name} cycle={reset_cycle}"
            )

    scenarios = [
        {
            "name": name,
            "description": description,
            "covered": bool(evidence[name]),
            "evidence": evidence[name],
        }
        for name, description in SCENARIOS
    ]
    covered_count = sum(scenario["covered"] for scenario in scenarios)
    return {
        "scenarios": scenarios,
        "summary": {
            "total_scenarios": len(scenarios),
            "covered_scenarios": covered_count,
            "uncovered_scenarios": len(scenarios) - covered_count,
            "coverage_percentage": round(100 * covered_count / len(scenarios), 2),
        },
    }


def write_regression_coverage_report(
    configurations: list[dict[str, Any]],
    seed: int,
    random_cycles: int,
    reports_dir: Path,
) -> Path:
    """Write a unique JSON report aggregating actual testbench scenario evidence."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    timestamp_tag = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    suffix = 0
    while True:
        stem = f"functional_coverage_{timestamp_tag}"
        if suffix:
            stem = f"{stem}_{suffix}"
        output_path = reports_dir / f"{stem}.json"
        try:
            with output_path.open("x", encoding="utf-8", newline="\n") as report_file:
                per_configuration = [
                    {
                        "configuration": config["configuration"],
                        "compilation_status": config["compilation_status"],
                        "simulation_status": config["simulation_status"],
                        "exit_code": config["exit_code"],
                        "trace_comparison": config["trace_comparison"],
                        "functional_coverage": config["functional_coverage"],
                    }
                    for config in configurations
                ]
                aggregate_scenarios = []
                for index, (name, description) in enumerate(SCENARIOS):
                    hits = []
                    for config in per_configuration:
                        scenario = config["functional_coverage"]["scenarios"][index]
                        if scenario["covered"]:
                            conf = config["configuration"]
                            hits.append(
                                {
                                    "configuration": f"{conf['FIFO_DEPTH']}x{conf['DATA_WIDTH']}",
                                    "evidence": scenario["evidence"],
                                }
                            )
                    aggregate_scenarios.append(
                        {
                            "name": name,
                            "description": description,
                            "covered": bool(hits),
                            "evidence": hits,
                        }
                    )
                covered = sum(item["covered"] for item in aggregate_scenarios)
                report = {
                    "schema_version": 1,
                    "generated_at": timestamp.isoformat(timespec="microseconds").replace(
                        "+00:00", "Z"
                    ),
                    "seed": seed,
                    "random_cycle_count": random_cycles,
                    "coverage_kind": "testbench functional scenario coverage, not code or silicon coverage",
                    "summary": {
                        "total_scenarios": len(SCENARIOS),
                        "covered_scenarios": covered,
                        "uncovered_scenarios": len(SCENARIOS) - covered,
                        "coverage_percentage": round(100 * covered / len(SCENARIOS), 2),
                    },
                    "scenarios": aggregate_scenarios,
                    "configurations": per_configuration,
                }
                json.dump(report, report_file, indent=2)
                report_file.write("\n")
            return output_path
        except FileExistsError:
            suffix += 1