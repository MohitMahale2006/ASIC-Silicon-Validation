"""Independent cycle-level model of the project's synchronous FIFO contract."""

from __future__ import annotations


class SynchronousFifoModel:
    """Software model advanced once per rising edge with the sampled inputs.

    Construction starts in the same state as after a reset edge. Reset is
    synchronous active-low; storage is intentionally not cleared by reset.
    """

    def __init__(self, depth: int = 16, data_width: int = 8):
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
            raise ValueError("depth must be a positive integer")
        if not isinstance(data_width, int) or isinstance(data_width, bool) or data_width < 1:
            raise ValueError("data_width must be a positive integer")

        self.depth = depth
        self.data_width = data_width
        self._data_mask = (1 << data_width) - 1
        self.storage: list[int | None] = [None] * depth
        self.read_pointer = 0
        self.write_pointer = 0
        self.occupancy = 0
        self.data_out = 0

    @property
    def full(self) -> bool:
        return self.occupancy == self.depth

    @property
    def empty(self) -> bool:
        return self.occupancy == 0

    def step(
        self,
        *,
        rst_n: bool,
        wr_en: bool = False,
        rd_en: bool = False,
        data_in: int = 0,
    ) -> dict[str, int | bool]:
        """Apply inputs sampled at one rising edge and return post-edge state."""
        if not isinstance(data_in, int) or isinstance(data_in, bool):
            raise TypeError("data_in must be an integer")

        if not rst_n:
            write_accepted = False
            read_accepted = False
            self.read_pointer = 0
            self.write_pointer = 0
            self.occupancy = 0
            self.data_out = 0
        else:
            # The RTL qualifies both requests from pre-edge status.
            write_accepted = bool(wr_en) and not self.full
            read_accepted = bool(rd_en) and not self.empty

            if read_accepted:
                read_value = self.storage[self.read_pointer]
                if read_value is None:
                    raise RuntimeError("model attempted to read an unwritten FIFO entry")
                self.data_out = read_value
                self.read_pointer = (self.read_pointer + 1) % self.depth

            if write_accepted:
                self.storage[self.write_pointer] = data_in & self._data_mask
                self.write_pointer = (self.write_pointer + 1) % self.depth

            if write_accepted and not read_accepted:
                self.occupancy += 1
            elif read_accepted and not write_accepted:
                self.occupancy -= 1

        return {
            "write_accepted": write_accepted,
            "read_accepted": read_accepted,
            "data_out": self.data_out,
            "occupancy": self.occupancy,
            "full": self.full,
            "empty": self.empty,
            "read_pointer": self.read_pointer,
            "write_pointer": self.write_pointer,
        }