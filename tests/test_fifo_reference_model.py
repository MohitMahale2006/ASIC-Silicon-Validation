"""Unit tests for the independent synchronous FIFO reference model."""

import random
import unittest

from verification.fifo_reference_model import SynchronousFifoModel


class SynchronousFifoModelTests(unittest.TestCase):
    def test_synchronous_active_low_reset_resets_state_but_preserves_storage(self):
        model = SynchronousFifoModel(depth=3, data_width=8)
        model.step(rst_n=True, wr_en=True, data_in=0xA5)
        stored_before_reset = list(model.storage)

        state = model.step(rst_n=False, wr_en=True, rd_en=True, data_in=0x5A)

        self.assertFalse(state["write_accepted"])
        self.assertFalse(state["read_accepted"])
        self.assertEqual(state["occupancy"], 0)
        self.assertTrue(state["empty"])
        self.assertFalse(state["full"])
        self.assertEqual(state["data_out"], 0)
        self.assertEqual(model.storage, stored_before_reset)

    def test_ordering_and_output_hold(self):
        model = SynchronousFifoModel(depth=3, data_width=8)
        for value in (0x11, 0x22):
            model.step(rst_n=True, wr_en=True, data_in=value)

        first_read = model.step(rst_n=True, rd_en=True)
        idle = model.step(rst_n=True)
        second_read = model.step(rst_n=True, rd_en=True)

        self.assertEqual(first_read["data_out"], 0x11)
        self.assertEqual(idle["data_out"], 0x11)
        self.assertEqual(second_read["data_out"], 0x22)
        self.assertTrue(second_read["empty"])

    def test_full_empty_and_rejected_requests(self):
        model = SynchronousFifoModel(depth=3, data_width=8)
        for value in (1, 2, 3):
            state = model.step(rst_n=True, wr_en=True, data_in=value)
        self.assertTrue(state["full"])

        rejected_write = model.step(rst_n=True, wr_en=True, data_in=99)
        self.assertFalse(rejected_write["write_accepted"])
        self.assertEqual(rejected_write["occupancy"], 3)
        self.assertEqual([model.step(rst_n=True, rd_en=True)["data_out"] for _ in range(3)], [1, 2, 3])

        rejected_read = model.step(rst_n=True, rd_en=True)
        self.assertFalse(rejected_read["read_accepted"])
        self.assertEqual(rejected_read["occupancy"], 0)
        self.assertTrue(rejected_read["empty"])

    def test_simultaneous_read_write_partial_empty_and_full(self):
        model = SynchronousFifoModel(depth=3, data_width=8)
        partial = SynchronousFifoModel(depth=3, data_width=8)
        partial.step(rst_n=True, wr_en=True, data_in=0xA1)
        partial.step(rst_n=True, wr_en=True, data_in=0xA2)
        state = partial.step(rst_n=True, wr_en=True, rd_en=True, data_in=0xA3)
        self.assertTrue(state["write_accepted"])
        self.assertTrue(state["read_accepted"])
        self.assertEqual(state["occupancy"], 2)
        self.assertEqual(state["data_out"], 0xA1)
        self.assertEqual(partial.step(rst_n=True, rd_en=True)["data_out"], 0xA2)
        self.assertEqual(partial.step(rst_n=True, rd_en=True)["data_out"], 0xA3)

        empty_state = model.step(rst_n=True, wr_en=True, rd_en=True, data_in=0x55)
        self.assertTrue(empty_state["write_accepted"])
        self.assertFalse(empty_state["read_accepted"])
        self.assertEqual(empty_state["occupancy"], 1)

        full_model = SynchronousFifoModel(depth=3, data_width=8)
        for value in (4, 5, 6):
            full_model.step(rst_n=True, wr_en=True, data_in=value)
        full_state = full_model.step(rst_n=True, wr_en=True, rd_en=True, data_in=7)
        self.assertFalse(full_state["write_accepted"])
        self.assertTrue(full_state["read_accepted"])
        self.assertEqual(full_state["occupancy"], 2)
        self.assertEqual(full_state["data_out"], 4)

    def test_pointer_wraparound_for_non_power_of_two_depth(self):
        model = SynchronousFifoModel(depth=3, data_width=8)
        for _ in range(2):
            for value in (10, 11, 12):
                model.step(rst_n=True, wr_en=True, data_in=value)
            for _ in range(3):
                model.step(rst_n=True, rd_en=True)
        self.assertEqual(model.read_pointer, 0)
        self.assertEqual(model.write_pointer, 0)
        self.assertEqual(model.occupancy, 0)

    def test_deterministic_randomized_invariants(self):
        def run(seed):
            rng = random.Random(seed)
            model = SynchronousFifoModel(depth=5, data_width=8)
            trace = []
            for _ in range(250):
                state = model.step(
                    rst_n=True,
                    wr_en=bool(rng.getrandbits(1)),
                    rd_en=bool(rng.getrandbits(1)),
                    data_in=rng.randrange(256),
                )
                self.assertGreaterEqual(state["occupancy"], 0)
                self.assertLessEqual(state["occupancy"], 5)
                self.assertEqual(state["full"], state["occupancy"] == 5)
                self.assertEqual(state["empty"], state["occupancy"] == 0)
                trace.append(state)
            return trace

        self.assertEqual(run(456), run(456))

    def test_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            SynchronousFifoModel(depth=0)
        with self.assertRaises(ValueError):
            SynchronousFifoModel(data_width=0)


if __name__ == "__main__":
    unittest.main()