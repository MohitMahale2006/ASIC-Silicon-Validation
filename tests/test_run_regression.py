"""Tests for multi-configuration FIFO regression orchestration."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_regression
from verification.fifo_reference_model import SynchronousFifoModel


def _passing_testbench_output(depth, data_width=8, seed=1):
    model = SynchronousFifoModel(depth=depth, data_width=data_width)
    lines = []
    cycle = 0

    def edge(test_name, *, rst_n=True, wr_en=False, rd_en=False, data_in=0):
        nonlocal cycle
        state = model.step(
            rst_n=rst_n, wr_en=wr_en, rd_en=rd_en, data_in=data_in
        )
        cycle += 1
        lines.append(
            f"PASS test={test_name} cycle={cycle} "
            f"full expected={int(state['full'])} actual={int(state['full'])} "
            f"empty expected={int(state['empty'])} actual={int(state['empty'])} "
            f"occupancy expected={state['occupancy']} actual={state['occupancy']} "
            f"data_out expected=0x{state['data_out']:x} actual=0x{state['data_out']:x}"
        )
        lines.append(
            "TRACE_JSON "
            + json.dumps(
                {
                    "cycle": cycle,
                    "test": test_name,
                    "rst_n": int(rst_n),
                    "wr_en": int(wr_en),
                    "rd_en": int(rd_en),
                    "data_in_hex": format(data_in, "x"),
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
        edge("write_pointer_wrap", wr_en=True, data_in=0x70 + iteration)
        edge("read_pointer_wrap", rd_en=True)
    edge("partial_simultaneous_setup", wr_en=True, data_in=0xA1)
    edge("partial_simultaneous_setup", wr_en=True, data_in=0xA2)
    edge("simultaneous_partially_occupied", wr_en=True, rd_en=True, data_in=0xA3)
    edge("reset_during_operation_setup", wr_en=True, data_in=0x5A)
    edge("reset_during_operation", rst_n=False)
    lines.append(f"PASS ALL FIFO TESTS cycles={cycle} seed={seed}")
    return "\n".join(lines)


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
        run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_passing_testbench_output(3), stderr=""
            ),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_passing_testbench_output(5, 16), stderr=""
            ),
        ]

        result = run_regression.run_regression(
            ((3, 8), (5, 16)), 7, 12, self.project_root, self.reports_dir
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(run.call_count, 4)
        self.assertTrue(Path(result["functional_coverage_report_path"]).exists())
        for config_result, expected in zip(result["configurations"], ((3, 8), (5, 16))):
            self.assertEqual(config_result["configuration"]["FIFO_DEPTH"], expected[0])
            self.assertEqual(config_result["configuration"]["DATA_WIDTH"], expected[1])
            self.assertEqual(config_result["compilation_status"], "success")
            self.assertEqual(config_result["simulation_status"], "success")
            self.assertEqual(config_result["trace_comparison"]["status"], "match")
            self.assertEqual(
                config_result["functional_coverage"]["summary"]["uncovered_scenarios"],
                0,
            )
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
                args=[], returncode=0, stdout=_passing_testbench_output(5, 16), stderr=""
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

    @mock.patch("scripts.run_regression.subprocess.run")
    @mock.patch("scripts.run_regression.shutil.which")
    def test_trace_mismatch_fails_configuration(self, which, run):
        which.side_effect = lambda tool: f"/tools/{tool}"
        mismatched_output = _passing_testbench_output(3).replace(
            '"data_out_hex": "1"', '"data_out_hex": "2"', 1
        )
        run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout=mismatched_output, stderr=""
            ),
        ]

        result = run_regression.run_regression(
            ((3, 8),), 1, 0, self.project_root, self.reports_dir
        )

        config = result["configurations"][0]
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(config["trace_comparison"]["status"], "mismatch")
        self.assertEqual(config["exit_code"], 5)

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