// Parameterized synchronous FIFO.
//
// Interface assumptions:
// - rst_n is active-low and synchronous to clk.
// - data_out updates only after an accepted read and otherwise holds its value.
// - Requests are accepted using full/empty status from before the rising edge.
// - No fall-through behavior: reads while empty are rejected, including a
//   simultaneous write. Writes while full are rejected, including a
//   simultaneous read.
// - DATA_WIDTH and DEPTH must both be positive integers.
module sync_fifo #(
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned DEPTH = 16
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         wr_en,
    input  logic                         rd_en,
    input  logic [DATA_WIDTH-1:0]        data_in,
    output logic [DATA_WIDTH-1:0]        data_out,
    output logic                         full,
    output logic                         empty,
    output logic [$clog2(DEPTH+1)-1:0]   occupancy
);

    localparam int unsigned PTR_WIDTH = (DEPTH > 1) ? $clog2(DEPTH) : 1;
    localparam int unsigned COUNT_WIDTH = $clog2(DEPTH + 1);

    logic [DATA_WIDTH-1:0] storage [0:DEPTH-1];
    logic [PTR_WIDTH-1:0] read_ptr;
    logic [PTR_WIDTH-1:0] write_ptr;

    logic write_accept;
    logic read_accept;

    assign full = (occupancy == COUNT_WIDTH'(DEPTH));
    assign empty = (occupancy == '0);
    assign write_accept = wr_en && !full;
    assign read_accept = rd_en && !empty;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            read_ptr  <= '0;
            write_ptr <= '0;
            occupancy <= '0;
            data_out  <= '0;
        end else begin
            if (write_accept) begin
                storage[write_ptr] <= data_in;
                if (write_ptr == PTR_WIDTH'(DEPTH - 1))
                    write_ptr <= '0;
                else
                    write_ptr <= write_ptr + 1'b1;
            end

            if (read_accept) begin
                data_out <= storage[read_ptr];
                if (read_ptr == PTR_WIDTH'(DEPTH - 1))
                    read_ptr <= '0;
                else
                    read_ptr <= read_ptr + 1'b1;
            end

            case ({write_accept, read_accept})
                2'b10: occupancy <= occupancy + 1'b1;
                2'b01: occupancy <= occupancy - 1'b1;
                default: occupancy <= occupancy;
            endcase
        end
    end

endmodule