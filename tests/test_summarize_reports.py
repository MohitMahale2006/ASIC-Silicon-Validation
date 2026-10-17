"""Focused tests for the validation-report summarizer."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts import summarize_reports


class SummarizeReportsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.reports_dir = Path(self.temporary_directory.name) / "reports"
        self.reports_dir.mkdir()
        self.summary_path = self.reports_dir / "validation_summary.md"

    def write_report(self, name, data):
        path = self.reports_dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_complete_success_is_pass_and_includes_recorded_fields(self):
        self.write_report(
            "validation_success.json",
            {
                "timestamp": "2026-10-17T12:00:00Z",
                "random_seed": 456,
                "random_cycle_count": 1000,
                "compilation_status": "success",
                "simulation_status": "success",
                "exit_code": 0,
                "elapsed_time_seconds": 0.25,
            },
        )

        self.assertTrue(
            summarize_reports.generate_summary(self.reports_dir, self.summary_path)
        )
        markdown = self.summary_path.read_text(encoding="utf-8")
        self.assertIn("| PASS |", markdown)
        self.assertIn("2026-10-17T12:00:00Z", markdown)
        self.assertIn("456", markdown)
        self.assertIn("1000", markdown)
        self.assertIn("0.250 s", markdown)

    def test_nonzero_exit_is_fail_even_when_stages_were_not_run(self):
        self.write_report(
            "validation_missing_tools.json",
            {
                "compilation_status": "not_run",
                "simulation_status": "not_run",
                "exit_code": 2,
            },
        )

        summarize_reports.generate_summary(self.reports_dir, self.summary_path)

        markdown = self.summary_path.read_text(encoding="utf-8")
        self.assertIn("| FAIL |", markdown)
        self.assertIn("not_run", markdown)

    def test_missing_result_fields_are_incomplete_not_pass(self):
        self.write_report(
            "validation_partial.json",
            {"timestamp": "2026-10-17T12:00:00Z", "random_seed": 12},
        )

        self.assertTrue(
            summarize_reports.generate_summary(self.reports_dir, self.summary_path)
        )
        markdown = self.summary_path.read_text(encoding="utf-8")
        self.assertIn("| INCOMPLETE |", markdown)
        self.assertIn("Not recorded", markdown)
        self.assertNotIn("| PASS |", markdown)

    def test_malformed_json_is_listed_and_no_usable_reports_returns_false(self):
        (self.reports_dir / "validation_broken.json").write_text(
            "{not valid json", encoding="utf-8"
        )

        self.assertFalse(
            summarize_reports.generate_summary(self.reports_dir, self.summary_path)
        )
        markdown = self.summary_path.read_text(encoding="utf-8")
        self.assertIn("No usable validation reports were found", markdown)
        self.assertIn("validation_broken.json", markdown)

    def test_empty_directory_returns_false_and_writes_helpful_summary(self):
        self.assertFalse(
            summarize_reports.generate_summary(self.reports_dir, self.summary_path)
        )
        self.assertIn(
            "python scripts/run_validation.py",
            self.summary_path.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()