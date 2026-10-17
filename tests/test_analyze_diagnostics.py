"""Unit tests for evidence-based validation diagnostic analysis."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts import analyze_diagnostics


class DiagnosticAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.input_dir = Path(self.temp.name) / "inputs"
        self.input_dir.mkdir()
        self.output = Path(self.temp.name) / "diagnostics.md"

    @staticmethod
    def valid_report(**overrides):
        data = {
            "timestamp": "2026-10-17T12:00:00Z",
            "compilation_status": "success",
            "simulation_status": "success",
            "exit_code": 0,
        }
        data.update(overrides)
        return data

    def write_json(self, name, value):
        path = self.input_dir / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_passing_validation_and_regression_extract_context(self):
        self.write_json(
            "validation_ok.json",
            self.valid_report(random_seed=456, random_cycle_count=1000),
        )
        self.write_json(
            "regression_d5_w16_ok.json",
            self.valid_report(
                random_seed=456,
                random_cycle_count=1000,
                configuration={"FIFO_DEPTH": 5, "DATA_WIDTH": 16},
            ),
        )

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["counts"], {"PASS": 2, "FAIL": 0, "INCOMPLETE": 0})
        markdown = self.output.read_text(encoding="utf-8")
        self.assertIn("successful_run", markdown)
        self.assertIn("456", markdown)
        self.assertIn("5 | 16", markdown)
        self.assertIn("not confirmed hardware or silicon root causes", markdown)

    def test_simulation_assertion_failure_is_evidence_based(self):
        self.write_json(
            "validation_failure.json",
            self.valid_report(
                simulation_status="failed",
                exit_code=4,
                error_details=[
                    {
                        "stage": "simulation",
                        "message": "Simulation failed",
                        "output": "FAIL test=read cycle=4 expected=0x11 actual=0x12",
                    }
                ],
                steps={"simulation": {"return_code": 1}},
            ),
        )

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["overall_status"], "FAIL")
        markdown = self.output.read_text(encoding="utf-8")
        self.assertIn("simulation_assertion_or_testbench_failure", markdown)
        self.assertIn("nonzero_simulation_exit", markdown)
        self.assertIn("FAIL test=read", markdown)

    def test_compiler_and_tool_error_categories(self):
        self.write_json(
            "validation_compile.json",
            self.valid_report(
                compilation_status="failed",
                simulation_status="not_run",
                exit_code=3,
                error_details=[{"stage": "compilation", "message": "syntax error"}],
            ),
        )
        self.write_json(
            "validation_tool.json",
            self.valid_report(
                compilation_status="not_run",
                simulation_status="not_run",
                exit_code=2,
                error_details=[{"stage": "tool_check", "message": "Missing vvp"}],
            ),
        )

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["counts"]["FAIL"], 2)
        markdown = self.output.read_text(encoding="utf-8")
        self.assertIn("compilation_or_tool_error", markdown)

    def test_missing_fields_and_incorrect_types_are_incomplete(self):
        self.write_json(
            "regression_incomplete.json",
            {
                "configuration": {"FIFO_DEPTH": "5", "DATA_WIDTH": 8},
                "compilation_status": "success",
                "simulation_status": "success",
                "exit_code": "0",
            },
        )

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["overall_status"], "INCOMPLETE")
        self.assertEqual(result["counts"]["INCOMPLETE"], 1)
        self.assertIn("incomplete_evidence", self.output.read_text(encoding="utf-8"))

    def test_malformed_json_is_incomplete_without_crashing(self):
        (self.input_dir / "validation_broken.json").write_text(
            "{not JSON", encoding="utf-8"
        )

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["exit_code"], 1)
        markdown = self.output.read_text(encoding="utf-8")
        self.assertIn("malformed_json", markdown)
        self.assertIn("validation_broken.json", markdown)

    def test_missing_input_directory_returns_incomplete_report(self):
        missing_dir = self.input_dir / "missing"

        result = analyze_diagnostics.analyze_directory(missing_dir, self.output)

        self.assertEqual(result["overall_status"], "INCOMPLETE")
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("does not exist", self.output.read_text(encoding="utf-8"))

    def test_nonzero_exit_is_fail_even_without_stage_failure(self):
        self.write_json("validation_exit.json", self.valid_report(exit_code=5))

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["overall_status"], "FAIL")
        self.assertIn("nonzero_validation_exit", self.output.read_text(encoding="utf-8"))

    def test_nonzero_compilation_step_return_code_is_failure(self):
        self.write_json(
            "validation_inconsistent.json",
            self.valid_report(
                steps={
                    "compilation": {"return_code": 1},
                    "simulation": {"return_code": 0},
                }
            ),
        )

        result = analyze_diagnostics.analyze_directory(self.input_dir, self.output)

        self.assertEqual(result["overall_status"], "FAIL")
        self.assertIn("compilation_or_tool_error", self.output.read_text())


if __name__ == "__main__":
    unittest.main()
