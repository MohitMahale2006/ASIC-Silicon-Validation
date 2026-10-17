# ASIC Silicon Validation and Automated Diagnostics Framework

> Portfolio project targeting ASIC design verification and silicon-enablement automation skills.

## Project Status

**Implemented:** synchronous FIFO RTL and self-checking testbench, Python validation/regression runners, fault injection, JSON-to-Markdown summaries, evidence-based diagnostic analysis, and GitHub Actions workflows. Local results must be generated and inspected; this README does not imply a current run or hosted CI result.

## Objective

Build and simulate a parameterized synchronous FIFO in synthesizable SystemVerilog, then automate run execution, report summarization, parameter regression, and controlled fault detection with Python.

## Scope and Validation Boundary

This is a laptop-runnable **pre-silicon simulation and automation project**, not validation of fabricated ASIC silicon. It does not establish FPGA behavior, timing closure, power, analog behavior, reliability, or production sign-off. Diagnostic categories are evidence-based hints from report data, not proven hardware root causes.

## Planned Repository Layout

- `rtl/`: synthesizable FIFO RTL
- `tb/`: self-checking SystemVerilog testbench
- `verification/`: reserved for future verification models/scenarios; no Python FIFO reference model is currently implemented
- `scripts/`: simulation orchestration, log analysis, and report generation
- `reports/`: generated validation artifacts only
- `tests/`: standard-library Python unit tests for the validation utilities
- `docs/`: architecture, test plan, and debugging guide
- `.github/workflows/`: continuous-integration workflow

## Design Contract

The initial architecture and behavioral assumptions are captured in [docs/architecture.md](docs/architecture.md). The test plan is in [docs/test_plan.md](docs/test_plan.md). These documents define the intended contract to implement and verify; they are not evidence that implementation or tests have run.

## Validation Workflow

1. Run the self-checking SystemVerilog testbench using Icarus Verilog.
2. Optionally run the five-configuration parameter regression or controlled fault-injection check.
3. Summarize recorded JSON results as Markdown or analyze evidence from a selected report directory.
4. Run the standard-library Python unit tests.

## Prerequisites and Commands

Requirements: Python 3.10+ and Icarus Verilog (`iverilog` and `vvp`). The runner and its unit tests use only Python's standard library. No FPGA board is needed. GTKWave is optional; the current testbench does not require waveform viewing.

### Install Python on Windows

Install Python 3.10 or newer from [python.org/downloads/windows](https://www.python.org/downloads/windows/). In the installer, enable **Add python.exe to PATH**, finish the installation, then open a new PowerShell terminal and confirm `python --version` reports Python 3.10 or newer. If the `python` command opens the Microsoft Store or is not found, disable the Python app execution aliases in Windows Settings or repair the installation with PATH enabled.

### Install Icarus Verilog on Windows

Install [MSYS2](https://www.msys2.org/), open its **UCRT64** terminal, and install the Icarus package:

```sh
pacman -S mingw-w64-ucrt-x86_64-iverilog
```

The package includes both `iverilog` and `vvp`. Either add `C:\msys64\ucrt64\bin` to Windows `PATH` and run from PowerShell, or run the project commands from the UCRT64 terminal. In MSYS2, change to the project directory with `cd /c/Users/<you>/path/to/ASIC`. For the current PowerShell session, you can instead run:

```powershell
$env:Path = "C:\msys64\ucrt64\bin;$env:Path"
python --version
Get-Command iverilog, vvp
```

### Run Validation

From the project root in PowerShell:

```powershell
Set-Location C:\Users\marat\OneDrive\Desktop\ASIC
python scripts/run_validation.py
python scripts/run_validation.py --seed 123 --random-cycles 500
```

Defaults are seed `1` and 100 randomized cycles, matching `tb/tb_sync_fifo.sv`. The runner checks both tools, compiles first, and skips simulation if tools are missing or compilation fails. It returns exit code 0 only if compilation and simulation both succeed.

For a reproducible 1,000-cycle run:

```powershell
python scripts/run_validation.py --seed 456 --random-cycles 1000
```

### Run a Parameter Regression

```powershell
python scripts/run_regression.py
python scripts/run_regression.py --config 3x8 --config 5x16 --seed 456 --random-cycles 1000
```

The default matrix is `(FIFO_DEPTH, DATA_WIDTH)`: `(5, 8)`, `(3, 8)`, `(5, 16)`, `(8, 32)`, and `(16, 8)`. Custom configurations use `DEPTHxWIDTH`; depth must be at least 3 because the existing self-checking testbench requires partial occupancy, and width must be positive. The regression passes only if every configuration compiles and the simulation exits zero with `PASS ALL FIFO TESTS`. Each config gets distinct timestamped JSON, log, and `.vvp` files under `reports/`; a failure in one config is recorded and does not prevent remaining configurations from running. The ordinary `run_validation.py` command remains the single default configuration path.

The regression runner returns nonzero if any requested configuration fails. The regression summarizer reads all matching reports in `reports/` by default, including historical runs; pass `--input-dir` to scope it to one run directory and `--output` to save a separate matrix.

### Run Opt-In Fault Injection

```powershell
python scripts/run_fault_injection.py
```

This command generates a temporary RTL copy with the read-data least-significant bit inverted; it never changes `rtl/sync_fifo.sv` or `tb/tb_sync_fifo.sv`. The testbench is expected to stop at `single_read_zero` with `expected=0x00 actual=0x01`. The harness reports detection success only when compilation succeeds, the simulator exits nonzero, and that exact diagnostic appears. Thus the simulator failure is expected, while the harness command itself exits zero for confirmed detection and nonzero for compile/tool errors or an undetected/unexpected failure. Fault-injection logs, JSON summaries, and compiled images use separate `fault_injection_*` names under `reports/`.

The nonzero simulator exit is the intended fault stimulus. It is not evidence of a physical FIFO or silicon failure.

### Run Python Unit Tests

```powershell
python -m unittest discover -s tests -v
```

### Generate and View a Validation Summary

```powershell
python scripts/summarize_reports.py
Get-Content reports/validation_summary.md
```

The summary classifies only reports with successful compilation, successful simulation, and exit code 0 as `PASS`. Explicit failures are `FAIL`; missing fields are `INCOMPLETE`. Malformed JSON files are listed. If no usable validation reports exist, the command writes a helpful summary and exits nonzero.

### Generate the Regression Matrix

```powershell
python scripts/summarize_regression.py
Get-Content reports/regression_matrix.md
```

The matrix reads per-configuration `regression_*.json` files and shows depth, data width, compile/simulation status, exit code, and result, with totals and an overall status. Malformed JSON files are listed separately; missing required fields are `INCOMPLETE`. It exits nonzero if any configuration fails or is incomplete, if reports are malformed, or if no usable regression reports exist.

### Analyze Validation Diagnostics

```powershell
python scripts/analyze_diagnostics.py --input-dir reports --output reports/diagnostic_analysis.md
Get-Content reports/diagnostic_analysis.md
```

The analyzer reads validation and regression JSON reports, distinguishes PASS, FAIL, and INCOMPLETE from recorded statuses and exit codes, and includes available configuration, seed/cycle, timestamp, and diagnostic-message context. Suggested categories such as tool/compile error, testbench failure, and nonzero simulation exit are evidence-based hints, not confirmed silicon root causes. It exits nonzero for any failed or incomplete report or unusable input. Extended CI analyzes its run-isolated JSON directory and uploads the Markdown report.

Without `--input-dir`, the analyzer scans all matching reports in `reports/`, including historical runs. For current-run-only analysis, select the isolated directory printed or created for that run:

```powershell
python scripts/analyze_diagnostics.py --input-dir reports/extended-validation-<run-id>-<attempt> --output reports/extended-validation-<run-id>-<attempt>/diagnostic_analysis.md
```

### Expected Outputs and Troubleshooting

Each validation run creates unique timestamped files under `reports/`: a `.log` containing the command, stdout, stderr, return codes, and step timings; a `.json` summary with availability/status/error metadata; and a compiled `.vvp` image after successful compilation. Existing report files are not intentionally replaced. A successful simulation should include `PASS ALL FIFO TESTS` in the log; the JSON must show compilation and simulation as `success`. A missing-tool or compile error is recorded and yields a nonzero exit code; inspect the report's `error_details` and log stderr. If PowerShell cannot find the commands after installation, add the MSYS2 UCRT64 `bin` directory to `PATH` or run inside the UCRT64 terminal.

## GitHub Actions

`.github/workflows/ci.yml` runs Python unit tests and single-run FIFO validation on pushes and pull requests. `.github/workflows/extended-validation.yml` additionally runs the five-configuration regression, report generation, controlled fault injection, and diagnostic analysis. The extended workflow runs on manual dispatch and on pushes or pull requests targeting `main`.

To inspect hosted results, open the repository's **Actions** tab, select the run and commit, then download the `extended-validation-evidence-*` artifact from the run summary. It contains run-isolated regression JSON/logs, the regression matrix, diagnostic report, and validation/fault evidence JSON/logs; compiled `.vvp` images are excluded. Workflow success must be confirmed from that actual Actions run; local results do not establish hosted CI status. Both workflows run the unit suite and normal validation for `main` events, so those checks currently execute twice.

## Limitations and Future Improvements

- This project verifies RTL in simulation; it does not validate fabricated ASIC silicon, FPGA behavior, timing, power, analog behavior, reliability, or production sign-off.
- The SystemVerilog testbench contains a queue scoreboard. A separate Python FIFO reference model, formal proof, and measured functional-coverage database are not implemented.
- Diagnostic categories are heuristics based on recorded report data and are not confirmed hardware root causes.
- The regression runner writes timestamped reports to the shared root `reports/` directory. Extended CI snapshots newly created outputs into a per-attempt directory; adding an output-directory option to the runner would remove that workflow-level collection step.
- High-value next steps include independent model checking, formal assertions, measured coverage goals, and a separate lab plan for eventual silicon evaluation.

## Results

Run-specific results belong in `reports/`; they are not checked into this README. The automated flow is pre-silicon simulation, not physical silicon validation, and makes no claim about fabricated devices, timing, power, or silicon coverage.
