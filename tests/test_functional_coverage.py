"""Tests for machine-readable SV trace comparison and scenario coverage."""

import json
import tempfile
import unittest
from pathlib import Path

from verification.fifo_reference_model import SynchronousFifoModel
from verification.functional_coverage import (
    SCENARIOS,
    collect_scenario_coverage,
    compare_trace_to_model,
    parse_trace_lines,
    write_regression_coverage_report,
)


def build_testbench_trace(depth=3):
    model = SynchronousFifoModel(depth=depth, data_width=8)
    lines = []
    cycle = 0

    def edge(test, *, rst_n=True, wr_en=False, rd_en=False, data_in=0):
        nonlocal cycle
        state = model.step(
            rst_n=rst_n, wr_en=wr_en, rd_en=rd_en, data_in=data_in
        )
        cycle += 1
        lines.append(
            "PASS test={test} cycle={cycle} occupancy expected={occupancy} actual={occupancy} "
            "full expected={full} actual={full} empty expected={empty} actual={empty} "
            "data_out expected=0x{data_out:02x} actual=0x{data_out:02x}".format(
                test=test,
                cycle=cycle,
                occupancy=state["occupancy"],
                full=int(state["full"]),
                empty=int(state["empty"]),
                data_out=state["data_out"],
            )
        )
        lines.append(
            "TRACE_JSON "
            + json.dumps(
                {
                    "cycle": cycle,
                    "test": test,
                    "rst_n": int(rst_n),
                    "wr_en": int(wr_en),
                    "rd_en": int(rd_en),
                    "data_in_hex": format(data_in & 0xFF, "x"),
                    "data_out_hex": format(state["data_out"], "x"),
                    "occupancy": state["occupancy"],
                    "full": int(state["full"]),
                    "empty": int(state["empty"]),
                }
            )
        )

    edge("initial_reset", rst_n=False)
    for value in range(depth):
        edge("fill_to_full", wr_en=True, data_in=value + 1)
    edge("write_rejected_when_full", wr_en=True, data_in=0xEE)
    for _ in range(depth):
        edge("drain_after_rejected_write", rd_en=True)
    edge("read_rejected_when_empty", rd_en=True)
    for iteration in range(depth + 2):
        edge("write_pointer_wrap", wr_en=True, data_in=0x30 + iteration)
        edge("read_pointer_wrap", rd_en=True)
    edge("partial_simultaneous_setup", wr_en=True, data_in=0xA1)
    edge("partial_simultaneous_setup", wr_en=True, data_in=0xA2)
    edge("simultaneous_partially_occupied", wr_en=True, rd_en=True, data_in=0xA3)
    edge("reset_during_operation_setup", wr_en=True, data_in=0x5A)
    edge("reset_during_operation", rst_n=False)
    lines.append(f"PASS ALL FIFO TESTS cycles={cycle} seed=7")
    return "\n".join(lines)


class FunctionalCoverageTests(unittest.TestCase):
    def test_trace_replays_against_reference_model(self):
        output = build_testbench_trace()

        result = compare_trace_to_model(output, depth=3, data_width=8)

        self.assertEqual(result["status"], "match")
        self.assertGreater(result["trace_records"], 0)
        self.assertEqual(result["mismatches"], [])

    def test_trace_mismatch_is_reported_with_cycle_and_signal(self):
        output = build_testbench_trace()
        output = output.replace('"data_out_hex": "1"', '"data_out_hex": "2"', 1)

        result = compare_trace_to_model(output, depth=3, data_width=8)

        self.assertEqual(result["status"], "mismatch")
        self.assertTrue(
            any(item["field"] == "data_out" for item in result["mismatches"])
        )

    def test_malformed_or_incomplete_trace_is_not_a_match(self):
        records, errors = parse_trace_lines(
            'TRACE_JSON {not-json}\nTRACE_JSON {"cycle": 1}'
        )
        self.assertEqual(records, [])
        self.assertEqual(len(errors), 2)
        result = compare_trace_to_model("TRACE_JSON {not-json}", 3, 8)
        self.assertEqual(result["status"], "incomplete")

    def test_scenarios_require_passing_named_testbench_evidence(self):
        coverage = collect_scenario_coverage(build_testbench_trace(), depth=3)

        self.assertEqual(coverage["summary"]["total_scenarios"], len(SCENARIOS))
        self.assertEqual(coverage["summary"]["covered_scenarios"], len(SCENARIOS))
        self.assertEqual(coverage["summary"]["uncovered_scenarios"], 0)
        self.assertTrue(all(item["covered"] for item in coverage["scenarios"]))

    def test_missing_scenario_evidence_remains_uncovered(self):
        coverage = collect_scenario_coverage(
            "PASS test=initial_reset cycle=1 occupancy expected=0 actual=0 "
            "full expected=0 actual=0 empty expected=1 actual=1 data_out expected=0x00 actual=0x00\n",
            depth=3,
        )

        by_name = {item["name"]: item for item in coverage["scenarios"]}
        self.assertFalse(by_name["fifo_reached_full"]["covered"])
        self.assertFalse(by_name["write_rejected_while_full"]["covered"])

    def test_machine_readable_coverage_report_has_summary_and_per_config_data(self):
        config_coverage = collect_scenario_coverage(build_testbench_trace(), depth=3)
        configuration = {
            "configuration": {"FIFO_DEPTH": 3, "DATA_WIDTH": 8},
            "compilation_status": "success",
            "simulation_status": "success",
            "exit_code": 0,
            "trace_comparison": {"status": "match", "trace_records": 1},
            "functional_coverage": config_coverage,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_regression_coverage_report(
                [configuration], 7, 10, Path(temp_dir)
            )
            report = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(report["summary"]["total_scenarios"], len(SCENARIOS))
        self.assertEqual(report["summary"]["covered_scenarios"], len(SCENARIOS))
        self.assertEqual(report["summary"]["coverage_percentage"], 100.0)
        self.assertEqual(report["configurations"][0]["configuration"]["FIFO_DEPTH"], 3)
        self.assertIn("not code or silicon coverage", report["coverage_kind"])


if __name__ == "__main__":
    unittest.main()