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

- Standard-library Python unit tests cover validation-runner and report-summarizer behavior; a separate Python FIFO reference model is not implemented yet.
- CI runs those unit tests and normal FIFO simulation. Fault injection remains opt-in and is not part of routine CI.

## Opt-In Fault-Injection Check

Run `python scripts/run_fault_injection.py` separately from normal validation. The harness mutates only a temporary RTL copy by inverting the read-data LSB. Expected evidence is a successful compile followed by a nonzero simulator exit containing `FAIL test=single_read_zero cycle=3 seed=1 data_out expected=0x00 actual=0x01`. A compile/tool error or a different simulation failure is not a detected fault. The harness returns zero only for the expected injected failure; the simulator itself must return nonzero. This check is intentionally excluded from routine CI so normal CI remains a pass-only validation run.

## Checks and Evidence

- The reference ring buffer models accepted operations using the documented pre-edge `full`/`empty` rules.
- `occupancy`, `full`, `empty`, and `data_out` are compared after each active clock edge; the reset check confirms reset value zero for `data_out`.
- Output data before the first reset edge is unspecified; the RTL contract defines `data_out` as zero after synchronous reset.
- Record the actual simulator command, tool/version when available, exit status, and logs. Do not report a pass unless the simulator output contains the testbench's final pass message and exits successfully.
- Keep generated logs, waveforms, and reports under `reports/`.

## Exit Criteria

The RTL simulation check is complete when compilation succeeds and the directed plus seeded-random testbench run exits successfully with its final pass message. Python unit tests, CI, physical-silicon validation, timing, power, and silicon-coverage claims are outside this testbench's exit criteria.

## Not in Initial Scope

FPGA bring-up, fabricated-device testing, analog/mixed-signal behavior, CDC verification, formal proof, gate-level timing simulation, synthesis sign-off, power analysis, and production-quality functional coverage closure.
