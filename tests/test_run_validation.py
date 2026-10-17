"""Unit tests for validation-runner argument and failure handling."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_validation


class ArgumentTests(unittest.TestCase):
    def test_seed_and_cycle_arguments(self):
        args = run_validation.build_parser().parse_args(
            ["--seed", "429", "--random-cycles", "25"]
        )
        self.assertEqual(args.seed, 429)
        self.assertEqual(args.random_cycles, 25)

    def test_defaults_match_testbench(self):
        args = run_validation.build_parser().parse_args([])
        self.assertEqual(args.seed, 1)
        self.assertEqual(args.random_cycles, 100)

    def test_invalid_seed_and_negative_cycle_count_are_rejected(self):
        parser = run_validation.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--seed", "4294967296"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--random-cycles", "-1"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="fifo project with spaces "
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.project_root = Path(self.temporary_directory.name) / "project root with spaces"
        self.reports_dir = self.project_root / "reports"

    def load_summary(self, result):
        summary_path = self.project_root / result["summary_file_path"]
        return json.loads(summary_path.read_text(encoding="utf-8"))

    @mock.patch("scripts.run_validation.subprocess.run")
    @mock.patch("scripts.run_validation.shutil.which")
    def test_missing_tool_stops_before_compile(self, which, run):
        which.side_effect = lambda tool: None if tool == "iverilog" else "vvp.exe"

        result = run_validation.run_validation(
            1, 100, self.project_root, self.reports_dir
        )

        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["compilation_status"], "not_run")
        self.assertEqual(result["simulation_status"], "not_run")
        run.assert_not_called()
        self.assertIn("iverilog", result["error_details"][0]["message"])
        self.assertEqual(self.load_summary(result)["exit_code"], 2)

    @mock.patch("scripts.run_validation.subprocess.run")
    @mock.patch("scripts.run_validation.shutil.which")
    def test_compile_failure_skips_simulation(self, which, run):
        which.side_effect = lambda tool: f"C:/Tools with spaces/{tool}.exe"
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="syntax error"
        )

        result = run_validation.run_validation(
            7, 12, self.project_root, self.reports_dir
        )

        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["compilation_status"], "failed")
        self.assertEqual(result["simulation_status"], "not_run")
        run.assert_called_once()
        self.assertIn("syntax error", (self.project_root / result["log_file_path"]).read_text())

    @mock.patch("scripts.run_validation.subprocess.run")
    @mock.patch("scripts.run_validation.shutil.which")
    def test_simulation_failure_is_reported(self, which, run):
        which.side_effect = lambda tool: f"C:/Tools/{tool}.exe"
        run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="test failed"
            ),
        ]

        result = run_validation.run_validation(
            9, 4, self.project_root, self.reports_dir
        )

        self.assertEqual(result["exit_code"], 4)
        self.assertEqual(result["compilation_status"], "success")
        self.assertEqual(result["simulation_status"], "failed")
        self.assertEqual(run.call_count, 2)
        self.assertIn("test failed", result["error_details"][0]["output"])

    @mock.patch("scripts.run_validation.subprocess.run")
    @mock.patch("scripts.run_validation.shutil.which")
    def test_success_uses_project_relative_sources_and_space_safe_cwd(self, which, run):
        which.side_effect = lambda tool: f"C:/Tools with spaces/{tool}.exe"
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="PASS", stderr=""
        )

        result = run_validation.run_validation(
            123, 20, self.project_root, self.reports_dir
        )

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["compilation_status"], "success")
        self.assertEqual(result["simulation_status"], "success")
        self.assertEqual(run.call_count, 2)

        compile_call = run.call_args_list[0]
        command = compile_call.args[0]
        self.assertEqual(compile_call.kwargs["cwd"], self.project_root.resolve())
        self.assertIn("rtl/sync_fifo.sv", command)
        self.assertIn("tb/tb_sync_fifo.sv", command)
        self.assertIn("reports/", command[command.index("-o") + 1])
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["+SEED=123", "+RANDOM_CYCLES=20"])
        self.assertEqual(self.load_summary(result)["random_seed"], 123)


if __name__ == "__main__":
    unittest.main()