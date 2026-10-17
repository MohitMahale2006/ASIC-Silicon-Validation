# ASIC Silicon Validation and Automated Diagnostics Framework

> Portfolio project targeting ASIC design verification and silicon-enablement automation skills.

## Project Status

**RTL, self-checking testbench, and Python simulation runner are implemented.** Run the documented commands locally to generate per-run reports. No simulation result is implied by this README.

## Objective

Build a parameterized synchronous FIFO in synthesizable SystemVerilog, verify its behavior with a SystemVerilog testbench and a Python reference model, then automate simulation execution, log diagnosis, and report generation.

## Scope and Validation Boundary

This initial project is a laptop-runnable **pre-silicon simulation and automation exercise**. It does not test fabricated silicon, an FPGA implementation, timing closure, analog behavior, or production sign-off. Future silicon validation would require appropriate devices, lab instrumentation, and a separate test methodology.

## Planned Repository Layout

- `rtl/`: synthesizable FIFO RTL
- `tb/`: self-checking SystemVerilog testbench
- `verification/`: Python reference model and scenario definitions
- `scripts/`: simulation orchestration, log analysis, and report generation
- `reports/`: generated validation artifacts only
- `tests/`: standard-library Python unit tests for the validation utilities
- `docs/`: architecture, test plan, and debugging guide
- `.github/workflows/`: continuous-integration workflow

## Design Contract

The initial architecture and behavioral assumptions are captured in [docs/architecture.md](docs/architecture.md). The test plan is in [docs/test_plan.md](docs/test_plan.md). These documents define the intended contract to implement and verify; they are not evidence that implementation or tests have run.

## Validation Workflow

1. Compile `rtl/sync_fifo.sv` and `tb/tb_sync_fifo.sv` with Icarus Verilog.
2. Run the simulator only after a successful compile.
3. Save a timestamped `.log`, `.json` summary, and compiled `.vvp` image under `reports/`.
4. Run the Python unit tests for argument parsing, tool/build failures, simulation failures, and paths containing spaces.

## Prerequisites and Commands

Requirements: Python 3.10+ and Icarus Verilog (`iverilog` and `vvp`). The runner and its unit tests use only Python's standard library. No FPGA board is needed. GTKWave is optional; the current testbench does not require waveform viewing.

### Install Python on Windows

Install Python 3.10 or newer from [python.org/downloads/windows](https://www.python.org/downloads/windows/). In the installer, enable **Add python.exe to PATH**, finish the installation, then open a new PowerShell terminal and confirm `python --version` reports Python 3.10 or newer. If the `python` command opens the Microsoft Store or is not found, disable the Python app execution aliases in Windows Settings or repair the installation with PATH enabled.

### Install Icarus Verilog on Windows

Install [MSYS2](https://www.msys2.org/), open its **UCRT64** terminal, and install the Icarus package:

```sh
pacman -S mingw-w64-ucrt-x86_64-iverilog
```

The package includes both `iverilog` and `vvp`. Either add `C:\msys64\ucrt64\bin` to Windows `PATH` and run from PowerShell, or run the project commands from the UCRT64 terminal. In MSYS2, change to the project directory with `cd /c/Users/<you>/path/to/ASIC`.

Check tool availability in PowerShell:

```powershell
Get-Command iverilog, vvp
```

### Run Validation

From the project root:

```powershell
python scripts/run_validation.py
python scripts/run_validation.py --seed 123 --random-cycles 500
```

Defaults are seed `1` and 100 randomized cycles, matching `tb/tb_sync_fifo.sv`. The runner checks both tools, compiles first, and skips simulation if tools are missing or compilation fails. It returns exit code 0 only if compilation and simulation both succeed.

### Run Opt-In Fault Injection

```powershell
python scripts/run_fault_injection.py
```

This command generates a temporary RTL copy with the read-data least-significant bit inverted; it never changes `rtl/sync_fifo.sv` or `tb/tb_sync_fifo.sv`. The testbench is expected to stop at `single_read_zero` with `expected=0x00 actual=0x01`. The harness reports detection success only when compilation succeeds, the simulator exits nonzero, and that exact diagnostic appears. Thus the simulator failure is expected, while the harness command itself exits zero for confirmed detection and nonzero for compile/tool errors or an undetected/unexpected failure. Fault-injection logs, JSON summaries, and compiled images use separate `fault_injection_*` names under `reports/`.

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

### Expected Outputs and Troubleshooting

Each validation run creates unique timestamped files under `reports/`: a `.log` containing the command, stdout, stderr, return codes, and step timings; a `.json` summary with availability/status/error metadata; and a compiled `.vvp` image after successful compilation. Existing report files are not intentionally replaced. A successful simulation should include `PASS ALL FIFO TESTS` in the log; the JSON must show compilation and simulation as `success`. A missing-tool or compile error is recorded and yields a nonzero exit code; inspect the report's `error_details` and log stderr. If PowerShell cannot find the commands after installation, add the MSYS2 UCRT64 `bin` directory to `PATH` or run inside the UCRT64 terminal.

## Results

Run-specific results belong in `reports/`; they are not checked into this README. The automated flow is pre-silicon simulation, not physical silicon validation, and makes no claim about fabricated devices, timing, power, or silicon coverage.
