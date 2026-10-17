# ASIC Silicon Validation and Automated Diagnostics Framework

A compact ASIC verification project focused on a parameterized synchronous FIFO, self-checking SystemVerilog validation, and Python-based evidence analysis for pre-silicon diagnostics.

## Overview

This repository implements and validates a synchronous FIFO in synthesizable SystemVerilog, then checks the design with a self-checking testbench and independent Python reference-model comparison. The goal is to create a small but realistic verification flow for RTL debugging, regression coverage tracking, and diagnostic reporting without claiming fabricated silicon validation or production sign-off.

The project is intentionally scoped to simulation-driven ASIC-style verification:

- RTL design under test: `rtl/sync_fifo.sv`
- Self-checking testbench: `tb/tb_sync_fifo.sv`
- Simulation toolchain: Icarus Verilog (`iverilog` and `vvp`)
- Independent Python reference model: `verification/fifo_reference_model.py`
- Trace comparison and scenario coverage: `verification/functional_coverage.py`
- Regression and diagnostic automation: `scripts/`

## Why this project matters

ASIC verification depends on the ability to turn an RTL model into evidence. This project demonstrates a practical workflow:

1. model the intended FIFO contract,
2. simulate real inputs through the RTL,
3. compare the observed outputs against an independent reference model,
4. record actual pass/fail evidence in machine-readable JSON, and
5. summarize results with diagnostics instead of assumptions.

This is relevant to silicon-validation internships because it shows experience with both RTL behavior and the engineering discipline behind regression, trace comparison, and evidence-driven debugging. It does not claim fabricated-chip testing, tape-out experience, or physical silicon validation.

## Architecture and workflow

```text
SystemVerilog FIFO RTL
        ↓
Self-checking testbench (directed + randomized scenarios)
        ↓
Icarus Verilog compile + simulation
        ↓
TRACE_JSON output from the testbench
        ↓
Independent Python FIFO reference model replay
        ↓
Trace comparison + functional scenario coverage
        ↓
JSON reports, regression data, and diagnostic analysis
```

### RTL and testbench

The FIFO is implemented in `rtl/sync_fifo.sv` and validated by `tb/tb_sync_fifo.sv`. The testbench includes:

- active-low synchronous reset behavior
- full/empty and occupancy checks
- ordered writes and reads
- rejected writes while full and rejected reads while empty
- pointer wraparound at non-power-of-two depths
- simultaneous read/write behavior under pre-edge acceptance rules
- deterministic random traffic driven by a seed and cycle count

The testbench records pass/fail evidence and emits machine-readable `TRACE_JSON` lines after successful checks.

### Independent Python model

The Python model in `verification/fifo_reference_model.py` implements the same contract as the RTL, including:

- synchronous active-low reset
- pre-edge acceptance using `full` and `empty`
- same-edge legal simultaneous read/write handling
- rejected operations
- hold behavior for `data_out` when no read is accepted
- occupancy, pointer, and status behavior

This model is intentionally independent from the SystemVerilog implementation and is used to compare recorded simulator traces against expected post-edge behavior.

### Functional coverage and reporting

The module in `verification/functional_coverage.py` does two things:

- replays each recorded `TRACE_JSON` entry through the Python model and compares it to the actual simulator output
- checks whether required FIFO scenarios were actually observed in the passing testbench evidence

These results are recorded in JSON under `reports/` and form the basis for coverage summaries and diagnostics.

## Tools and technologies

- SystemVerilog for RTL and testbench implementation
- Python 3.10+ for runners, analysis, model comparison, and coverage logic
- Icarus Verilog for compiling and running the RTL simulation (`iverilog`, `vvp`)
- Git for repository management
- GitHub Actions for CI and extended validation workflow automation

## Verified regression results

The current generated regression output confirms the following results from the project’s current run:

- 5x8: 159 trace records matched
- 3x8: 147 trace records matched
- 5x16: 159 trace records matched
- 8x32: 177 trace records matched
- 16x8: 225 trace records matched
- 8 of 8 required scenarios covered in each configuration
- 53 Python unit tests passed

The coverage report is stored under `reports/functional_coverage_*.json` and the current run shows 100% scenario coverage for the implemented FIFO behaviors.

## Fault injection demonstration

The project includes a deliberate fault-injection harness in `scripts/run_fault_injection.py`.

This harness creates a temporary RTL copy and flips the least-significant bit of an accepted read value. The known expected failure is:

```text
FAIL test=single_read_zero cycle=3 seed=1 data_out expected=0x00 actual=0x01
```

The project’s generated fault-injection report confirms the expected behavior:

- faulty simulation return code: `1`
- framework detection status: `fault_detected`
- framework exit code: `0`

This is intentional: the simulator is expected to fail under the injected fault, while the fault-injection framework itself returns zero only when it confirms the expected failure signature was detected.

## Setup and requirements

### Python

Install Python 3.10 or later from the official Python website and ensure `python` is on `PATH`.

### Icarus Verilog on Windows

Install MSYS2 and then install the Icarus package in the UCRT64 environment:

```powershell
pacman -S mingw-w64-ucrt-x86_64-iverilog
```

For the current PowerShell session, add the UCRT64 tools to `PATH`:

```powershell
$env:Path = "C:\msys64\ucrt64\bin;$env:Path"
python --version
Get-Command iverilog, vvp
```

If `iverilog` or `vvp` is not found, the project scripts will report missing tools instead of continuing with a failed compile.

## Commands

From the repository root:

### Unit tests

```powershell
python -m unittest discover -s tests -v
```

### Single validation run

```powershell
python scripts/run_validation.py
python scripts/run_validation.py --seed 123 --random-cycles 500
```

### Parameter regression

```powershell
python scripts/run_regression.py
python scripts/run_regression.py --config 3x8 --config 5x16 --seed 456 --random-cycles 1000
```

The default regression matrix is:

- 5x8
- 3x8
- 5x16
- 8x32
- 16x8

### Fault injection

```powershell
python scripts/run_fault_injection.py
```

### Diagnostic analysis

```powershell
python scripts/analyze_diagnostics.py --input-dir reports --output reports/diagnostic_analysis.md
```

## Report locations

Generated artifacts are placed under `reports/`:

- `validation_*.json` and `validation_*.log`
- `regression_*.json`, `regression_*.log`, and `regression_*.vvp`
- `functional_coverage_*.json`
- `fault_injection_*.json` and `fault_injection_*.log`
- `regression_matrix.md`
- `validation_summary.md`
- `diagnostic_analysis.md`

These files capture the actual simulator commands, return codes, pass/fail evidence, trace records, and coverage summary.

## Troubleshooting

- If Python cannot import `verification`, ensure you are running the command from the repository root.
- If `iverilog` is not found, add `C:\msys64\ucrt64\bin` to `PATH` for the current session.
- If a regression fails due to a trace mismatch, inspect the `trace_comparison` section in the matching JSON report.
- If a scenario is not counted as covered, inspect the JSON coverage report and the original `TRACE_JSON` lines used to produce that result.
- Keep generated reports under `reports/`; do not rewrite historical artifacts to create a false pass.

## Relevance to silicon validation internships

This project demonstrates a realistic pre-silicon verification flow: RTL design, self-checking validation, trace-based model comparison, functional coverage analysis, and evidence reporting. It is relevant to ASIC and silicon-validation internship work because it shows disciplined verification practice, regression automation, and the ability to interpret real tooling output rather than relying on assumptions.

It is intentionally limited to simulation and diagnostics; it does not claim physical silicon testing, tape-out experience, or production hardware sign-off.

## Repository layout

- `rtl/` — synthesizable FIFO RTL
- `tb/` — SystemVerilog testbench
- `verification/` — Python reference model and trace comparison logic
- `scripts/` — simulation, regression, and diagnostics automation
- `reports/` — generated evidence and summaries
- `tests/` — standard-library Python unit tests
- `docs/` — architecture and test-plan documentation
- `.github/workflows/` — CI and extended-validation workflows

## Verified command

The following command was verified locally with exit code 0:

```powershell
python -m unittest discover -s tests -v
```

This run reported 53 tests passed.
