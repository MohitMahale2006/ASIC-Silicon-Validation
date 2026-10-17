"""Tests for the regression matrix Markdown generator."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import summarize_regression


class SummarizeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.reports_dir = Path(self.temporary_directory.name) / "reports"
        self.reports_dir.mkdir()
        self.output_path = self.reports_dir / "regression_matrix.md"

    def write_report(self, name, data):
        path = self.reports_dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    @staticmethod
    def report(depth=5, width=8, **overrides):
        data = {
            "timestamp": "2026-10-17T12:00:00Z",
            "configuration": {"FIFO_DEPTH": depth, "DATA_WIDTH": width},
            "compilation_status": "success",
            "simulation_status": "success",
            "exit_code": 0,
            "elapsed_time_seconds": 0.1,
        }
        data.update(overrides)
        return data

    def test_all_pass_configurations_and_totals(self):
        self.write_report("regression_d3_w8_a.json", self.report(3, 8))
        self.write_report("regression_d5_w16_b.json", self.report(5, 16))

        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["totals"], {"PASS": 2, "FAIL": 0, "INCOMPLETE": 0})
        markdown = self.output_path.read_text(encoding="utf-8")
        self.assertIn("FIFO Regression Matrix", markdown)
        self.assertIn("Generated at:", markdown)
        self.assertIn("2 passed, 0 failed, 0 incomplete", markdown)
        self.assertIn("| 3 | 8 | success | success | 0 | PASS |", markdown)

    def test_explicit_simulation_failure_is_fail(self):
        self.write_report(
            "regression_d5_w8_fail.json",
            self.report(simulation_status="failed", exit_code=4),
        )

        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["overall_status"], "FAIL")
        self.assertEqual(result["totals"]["FAIL"], 1)
        self.assertIn("| 5 | 8 | success | failed | 4 | FAIL |", self.output_path.read_text())

    def test_compilation_failure_is_fail_without_passed_simulation(self):
        self.write_report(
            "regression_d3_w8_compile.json",
            self.report(compilation_status="failed", simulation_status="not_run", exit_code=3),
        )

        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["overall_status"], "FAIL")
        self.assertEqual(result["totals"]["FAIL"], 1)

    def test_missing_required_fields_are_incomplete(self):
        self.write_report(
            "regression_partial.json",
            {"configuration": {"FIFO_DEPTH": 5}, "exit_code": 0},
        )

        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["overall_status"], "INCOMPLETE")
        self.assertEqual(result["totals"]["INCOMPLETE"], 1)
        markdown = self.output_path.read_text(encoding="utf-8")
        self.assertIn("Not recorded", markdown)
        self.assertIn("INCOMPLETE", markdown)

    def test_malformed_json_is_reported_and_makes_overall_incomplete(self):
        self.write_report("regression_d5_w8_ok.json", self.report())
        (self.reports_dir / "regression_broken.json").write_text(
            "{not JSON", encoding="utf-8"
        )

        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["overall_status"], "INCOMPLETE")
        self.assertEqual(result["malformed_report_count"], 1)
        self.assertIn("regression_broken.json", self.output_path.read_text())

    def test_no_usable_reports_writes_helpful_report_and_returns_nonzero(self):
        (self.reports_dir / "regression_broken.json").write_text(
            "not JSON", encoding="utf-8"
        )

        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["overall_status"], "INCOMPLETE")
        self.assertNotEqual(result["exit_code"], 0)
        markdown = self.output_path.read_text(encoding="utf-8")
        self.assertIn("No usable regression JSON reports", markdown)
        self.assertIn("regression_broken.json", markdown)

    def test_empty_directory_writes_helpful_report_and_returns_nonzero(self):
        result = summarize_regression.generate_matrix(
            self.reports_dir, self.output_path
        )

        self.assertEqual(result["report_count"], 0)
        self.assertEqual(result["exit_code"], 1)
        self.assertIn(
            "python scripts/run_regression.py",
            self.output_path.read_text(encoding="utf-8"),
        )

    def test_cli_selects_input_directory_and_output_path(self):
        selected_dir = self.reports_dir / "current_run"
        selected_dir.mkdir()
        self.write_report("regression_old_fail.json", self.report(simulation_status="failed"))
        (selected_dir / "regression_current.json").write_text(
            json.dumps(self.report(3, 16)), encoding="utf-8"
        )
        selected_output = self.reports_dir / "current_run_matrix.md"

        exit_code = summarize_regression.main(
            ["--input-dir", str(selected_dir), "--output", str(selected_output)]
        )

        self.assertEqual(exit_code, 0)
        markdown = selected_output.read_text(encoding="utf-8")
        self.assertIn("regression_current.json", markdown)
        self.assertNotIn("regression_old_fail.json", markdown)

    def test_cli_defaults_preserve_reports_directory_and_matrix_path(self):
        self.write_report("regression_default.json", self.report())

        with (
            mock.patch.object(
                summarize_regression, "REPORTS_DIR", self.reports_dir
            ),
            mock.patch.object(
                summarize_regression, "SUMMARY_PATH", self.output_path
            ),
        ):
            exit_code = summarize_regression.main([])

        self.assertEqual(exit_code, 0)
        self.assertTrue(self.output_path.exists())
        self.assertIn("regression_default.json", self.output_path.read_text())


if __name__ == "__main__":
    unittest.main()