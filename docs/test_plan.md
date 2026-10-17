# Test Plan: Synchronous FIFO

## Goals

Verify the implemented FIFO transaction contract with a self-checking SystemVerilog testbench and a software reference queue. These are pre-silicon simulation tests, not physical silicon validation.

## Implemented RTL Testbench

`tb/tb_sync_fifo.sv` instantiates the existing `sync_fifo` with an 8-bit data path and default test depth 5. The non-power-of-two depth exercises explicit pointer wrap. It drives inputs on falling edges, updates the reference model at rising edges, and checks outputs after the DUT's nonblocking assignments settle. The testbench terminates with `$fatal(1, ...)` on the first mismatch and includes test name, cycle, expected value, and actual value in failures.

Implemented directed scenarios:

1. Synchronous active-low reset clears occupancy and `data_out`, asserts `empty`, and deasserts `full`.
2. Single write/read transfers of `0x00` and `0xFF`.
3. Multiple writes and reads with FIFO ordering checks.
4. Occupancy increment/decrement and status checks after every transaction.
5. Fill to full and drain to empty boundary transitions.
6. Rejected write while full, followed by draining to prove existing entries were preserved.
7. Rejected read while empty without occupancy change.
8. Repeated write/read traffic through pointer wrap.
9. Simultaneous read/write while partially occupied, checking returned head and stable occupancy.
10. Simultaneous requests while empty (write accepted, read rejected) and while full (read accepted, write rejected), following pre-edge flags.
11. Reset while populated followed by a post-reset transfer.
12. Deterministic LCG-based randomized read/write requests.

The random seed and number of randomized cycles can be overridden with `+SEED=<decimal>` and `+RANDOM_CYCLES=<decimal>`. Defaults are seed 1 and 100 cycles. The testbench requires `FIFO_DEPTH >= 3` for its partial-occupancy scenario; its default is 5.

## Current Automation Test Layers

- Standard-library Python unit tests cover the validation and regression runners, fault-injection classification, report summaries, and diagnostic analysis. The FIFO scoreboard is in the SystemVerilog testbench; no separate Python FIFO reference model exists.
- Basic CI runs unit tests and normal FIFO simulation. Extended CI also runs the five-config regression, regression matrix, controlled fault detection, and current-run diagnostic analysis, then uploads report evidence.

## Parameter Regression

Run `python scripts/run_regression.py` for the default `(FIFO_DEPTH, DATA_WIDTH)` matrix: `(5, 8)`, `(3, 8)`, `(5, 16)`, `(8, 32)`, and `(16, 8)`. To select a subset, repeat `--config DEPTHxWIDTH`, for example `python scripts/run_regression.py --config 3x8 --config 5x16`. Icarus overrides the testbench top-level parameters using `-P tb_sync_fifo.FIFO_DEPTH=<depth>` and `-P tb_sync_fifo.DATA_WIDTH=<width>`; the RTL remains unchanged. The testbench supports depth >= 3 and positive data widths.

Every configuration receives its own timestamped JSON summary, log, and compiled image under `reports/`. A regression passes only when all requested configs compile, each simulation exits zero, and each output contains the testbench's `PASS ALL FIFO TESTS` marker. Compile errors skip simulation for that config, are recorded with the compiler return code, and cause an overall nonzero exit. Other configs continue so the report identifies all outcomes.

Generate a Markdown matrix with `python scripts/summarize_regression.py`; view it with `Get-Content reports/regression_matrix.md`. The report contains the generation timestamp, per-config depth/width and stage statuses, exit code, PASS/FAIL/INCOMPLETE result, totals, and overall status. For example, complete success requires both stage statuses `success` and exit code `0`; compile failures are FAIL, missing fields are INCOMPLETE, and malformed JSON filenames are listed separately. Any failure, incomplete record, malformed report, or empty report set gives the summary command a nonzero exit.

## Opt-In Fault-Injection Check

Run `python scripts/run_fault_injection.py` separately from normal validation. The harness mutates only a temporary RTL copy by inverting the read-data LSB. Expected evidence is a successful compile followed by a nonzero simulator exit containing `FAIL test=single_read_zero cycle=3 seed=1 data_out expected=0x00 actual=0x01`. A compile/tool error or a different simulation failure is not a detected fault. The harness returns zero only for the expected injected failure; the simulator itself must return nonzero. Basic CI omits fault injection; the extended workflow runs it and passes only when the harness confirms the expected diagnostic.

## Checks and Evidence

- The reference ring buffer models accepted operations using the documented pre-edge `full`/`empty` rules.
- `occupancy`, `full`, `empty`, and `data_out` are compared after each active clock edge; the reset check confirms reset value zero for `data_out`.
- Output data before the first reset edge is unspecified; the RTL contract defines `data_out` as zero after synchronous reset.
- Record the actual simulator command, tool/version when available, exit status, and logs. Do not report a pass unless the simulator output contains the testbench's final pass message and exits successfully.
- Keep generated logs, waveforms, and reports under `reports/`.

## Exit Criteria

The RTL simulation check is complete when compilation succeeds and the directed plus seeded-random testbench run exits successfully with its final pass message. Python unit tests and CI have separate exit criteria. Physical-silicon validation, timing, power, and silicon-coverage claims are outside this simulation plan.

## Not in Initial Scope

FPGA bring-up, fabricated-device testing, analog/mixed-signal behavior, CDC verification, formal proof, gate-level timing simulation, synthesis sign-off, power analysis, and production-quality functional coverage closure.
