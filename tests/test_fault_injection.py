"""Unit tests for isolated FIFO fault injection and result classification."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_fault_injection


class FaultInjectionTests(unittest.TestCase):
    def test_mutation_flips_read_data_lsb_without_changing_original(self):
        original = "data_out <= storage[read_ptr];"

        faulty = run_fault_injection.inject_read_data_fault(original)

        self.assertEqual(original, "data_out <= storage[read_ptr];")
        self.assertIn("^ {{(DATA_WIDTH-1){1'b0}}, 1'b1}", faulty)

    def test_mutation_requires_exactly_one_known_read_assignment(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            run_fault_injection.inject_read_data_fault("module unrelated; endmodule")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            run_fault_injection.inject_read_data_fault(
                "data_out <= storage[read_ptr];\ndata_out <= storage[read_ptr];"
            )

    def test_expected_diagnostic_and_nonzero_simulation_is_detected(self):
        result = run_fault_injection.classify_fault_result(
            0, 1, run_fault_injection.EXPECTED_DIAGNOSTIC
        )
        self.assertEqual(result, "fault_detected")

    def test_compile_failure_never_counts_as_fault_detection(self):
        result = run_fault_injection.classify_fault_result(1, None, "syntax error")
        self.assertEqual(result, "compile_error")

    def test_zero_exit_or_unexpected_failure_is_not_fault_detection(self):
        self.assertEqual(
            run_fault_injection.classify_fault_result(
                0, 0, run_fault_injection.EXPECTED_DIAGNOSTIC
            ),
            "fault_not_detected",
        )
        self.assertEqual(
            run_fault_injection.classify_fault_result(0, 1, "unrelated failure"),
            "unexpected_simulation_failure",
        )

    @mock.patch("scripts.run_fault_injection.subprocess.run")
    @mock.patch("scripts.run_fault_injection.shutil.which")
    def test_compile_error_does_not_run_simulator(self, which, run):
        which.side_effect = lambda tool: f"/tools/{tool}"
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="compile error"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "rtl").mkdir()
            (root / "tb").mkdir()
            (root / "rtl" / "sync_fifo.sv").write_text(
                "data_out <= storage[read_ptr];", encoding="utf-8"
            )
            (root / "tb" / "tb_sync_fifo.sv").write_text("", encoding="utf-8")
            with (
                mock.patch.object(run_fault_injection, "PROJECT_ROOT", root),
                mock.patch.object(run_fault_injection, "RTL_PATH", root / "rtl" / "sync_fifo.sv"),
                mock.patch.object(run_fault_injection, "TESTBENCH_PATH", root / "tb" / "tb_sync_fifo.sv"),
                mock.patch.object(run_fault_injection, "REPORTS_DIR", root / "reports"),
            ):
                result = run_fault_injection.run_fault_injection()

        self.assertEqual(result["detection_status"], "compile_error")
        self.assertEqual(result["exit_code"], 2)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()