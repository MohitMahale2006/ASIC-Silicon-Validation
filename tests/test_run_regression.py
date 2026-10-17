"""Tests for multi-configuration FIFO regression orchestration."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_regression


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.project_root = Path(self.temporary_directory.name) / "project"
        self.reports_dir = self.project_root / "reports"

    @mock.patch("scripts.run_regression.subprocess.run")
    @mock.patch("scripts.run_regression.shutil.which")
    def test_successful_multiple_configurations(self, which, run):
        which.side_effect = lambda tool: f"/tools/{tool}"
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="PASS ALL FIFO TESTS cycles=59 seed=1", stderr=""
        )

        result = run_regression.run_regression(
            ((3, 8), (5, 16)), 7, 12, self.project_root, self.reports_dir
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(run.call_count, 4)
        for config_result, expected in zip(result["configurations"], ((3, 8), (5, 16))):
            self.assertEqual(config_result["configuration"]["FIFO_DEPTH"], expected[0])
            self.assertEqual(config_result["configuration"]["DATA_WIDTH"], expected[1])
            self.assertEqual(config_result["compilation_status"], "success")
            self.assertEqual(config_result["simulation_status"], "success")
            report_path = self.project_root / config_result["summary_file_path"]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["exit_code"], 0)

        compile_args = run.call_args_list[0].args[0]
        self.assertIn("tb_sync_fifo.FIFO_DEPTH=3", compile_args)
        self.assertIn("tb_sync_fifo.DATA_WIDTH=8", compile_args)
        self.assertEqual(
            run.call_args_list[1].args[0][-2:], ["+SEED=7", "+RANDOM_CYCLES=12"]
        )
        self.assertNotEqual(
            result["configurations"][0]["summary_file_path"],
            result["configurations"][1]["summary_file_path"],
        )

    @mock.patch("scripts.run_regression.subprocess.run")
    @mock.patch("scripts.run_regression.shutil.which")
    def test_failed_compile_fails_regression_and_skips_that_simulation(self, which, run):
        which.side_effect = lambda tool: f"/tools/{tool}"
        run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad config"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout="PASS ALL FIFO TESTS", stderr=""
            ),
        ]

        result = run_regression.run_regression(
            ((3, 8), (5, 16)), 1, 10, self.project_root, self.reports_dir
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["configurations"][0]["compilation_status"], "failed")
        self.assertEqual(result["configurations"][0]["simulation_status"], "not_run")
        self.assertEqual(result["configurations"][0]["exit_code"], 3)
        self.assertEqual(result["configurations"][1]["simulation_status"], "success")
        self.assertEqual(run.call_count, 3)

    def test_invalid_config_arguments_are_rejected(self):
        parser = run_regression.build_parser()
        for value in ("bad", "2x8", "5x0"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                parser.parse_args(["--config", value])

    @mock.patch("scripts.run_regression.subprocess.run")
    @mock.patch("scripts.run_regression.shutil.which", return_value=None)
    def test_missing_tools_fail_every_configuration_without_compiling(self, which, run):
        result = run_regression.run_regression(
            ((3, 8),), 1, 0, self.project_root, self.reports_dir
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["configurations"][0]["exit_code"], 2)
        self.assertEqual(result["configurations"][0]["compilation_status"], "not_run")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()