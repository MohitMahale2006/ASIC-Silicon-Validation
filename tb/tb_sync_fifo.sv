`timescale 1ns/1ps

module tb_sync_fifo #(
    parameter integer FIFO_DEPTH = 5,
    parameter integer DATA_WIDTH = 8
);

    localparam integer COUNT_WIDTH = $clog2(FIFO_DEPTH + 1);

    logic clk;
    logic rst_n;
    logic wr_en;
    logic rd_en;
    logic [DATA_WIDTH-1:0] data_in;
    logic [DATA_WIDTH-1:0] data_out;
    logic full;
    logic empty;
    logic [COUNT_WIDTH-1:0] occupancy;

    logic [DATA_WIDTH-1:0] model_storage [0:FIFO_DEPTH-1];
    integer model_head;
    integer model_tail;
    integer model_count;
    logic [DATA_WIDTH-1:0] model_data_out;
    integer cycle_number;

    reg [31:0] random_state;
    reg [31:0] initial_seed;
    integer random_cycles;
    integer iteration;
    integer seed_was_set;

    sync_fifo #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(FIFO_DEPTH)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .wr_en(wr_en),
        .rd_en(rd_en),
        .data_in(data_in),
        .data_out(data_out),
        .full(full),
        .empty(empty),
        .occupancy(occupancy)
    );

    initial clk = 1'b0;
    always #5 clk = ~clk;

    function [31:0] next_random;
        input [31:0] state;
        begin
            next_random = (state * 32'd1664525) + 32'd1013904223;
        end
    endfunction

    task automatic check_outputs;
        input string test_name;
        reg expected_full;
        reg expected_empty;
        begin
            expected_full = (model_count == FIFO_DEPTH);
            expected_empty = (model_count == 0);

            if (occupancy !== model_count)
                $fatal(1,
                    "FAIL test=%s cycle=%0d seed=%0d occupancy expected=%0d actual=%0d",
                    test_name, cycle_number, initial_seed, model_count, occupancy);
            if (full !== expected_full)
                $fatal(1,
                    "FAIL test=%s cycle=%0d seed=%0d full expected=%b actual=%b",
                    test_name, cycle_number, initial_seed, expected_full, full);
            if (empty !== expected_empty)
                $fatal(1,
                    "FAIL test=%s cycle=%0d seed=%0d empty expected=%b actual=%b",
                    test_name, cycle_number, initial_seed, expected_empty, empty);
            if (data_out !== model_data_out)
                $fatal(1,
                    "FAIL test=%s cycle=%0d seed=%0d data_out expected=0x%02x actual=0x%02x",
                    test_name, cycle_number, initial_seed, model_data_out, data_out);

            $display(
                "PASS test=%s cycle=%0d occupancy expected=%0d actual=%0d full expected=%b actual=%b empty expected=%b actual=%b data_out expected=0x%02x actual=0x%02x",
                test_name, cycle_number, model_count, occupancy,
                expected_full, full, expected_empty, empty,
                model_data_out, data_out);
        end
    endtask

    task automatic emit_trace;
        input string test_name;
        begin
            $display(
                "TRACE_JSON {\"cycle\":%0d,\"test\":\"%s\",\"rst_n\":%0d,\"wr_en\":%0d,\"rd_en\":%0d,\"data_in_hex\":\"%0h\",\"data_out_hex\":\"%0h\",\"occupancy\":%0d,\"full\":%0d,\"empty\":%0d}",
                cycle_number, test_name, rst_n, wr_en, rd_en, data_in,
                data_out, occupancy, full, empty);
        end
    endtask

    task automatic apply_cycle;
        input logic do_write;
        input logic do_read;
        input logic [DATA_WIDTH-1:0] write_value;
        input string test_name;
        reg write_accepted;
        reg read_accepted;
        begin
            @(negedge clk);
            rst_n = 1'b1;
            wr_en = do_write;
            rd_en = do_read;
            data_in = write_value;

            write_accepted = do_write && (model_count < FIFO_DEPTH);
            read_accepted = do_read && (model_count > 0);

            @(posedge clk);
            if (read_accepted) begin
                model_data_out = model_storage[model_head];
                model_head = (model_head + 1) % FIFO_DEPTH;
                model_count = model_count - 1;
            end
            if (write_accepted) begin
                model_storage[model_tail] = write_value;
                model_tail = (model_tail + 1) % FIFO_DEPTH;
                model_count = model_count + 1;
            end

            cycle_number = cycle_number + 1;
            #1;
            check_outputs(test_name);
            emit_trace(test_name);
        end
    endtask

    task automatic apply_reset;
        input string test_name;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            wr_en = 1'b0;
            rd_en = 1'b0;
            data_in = '0;
            @(posedge clk);
            model_head = 0;
            model_tail = 0;
            model_count = 0;
            model_data_out = '0;
            cycle_number = cycle_number + 1;
            #1;
            check_outputs(test_name);
            emit_trace(test_name);
        end
    endtask

    initial begin
        rst_n = 1'b1;
        wr_en = 1'b0;
        rd_en = 1'b0;
        data_in = '0;
        model_head = 0;
        model_tail = 0;
        model_count = 0;
        model_data_out = '0;
        cycle_number = 0;
        random_state = 32'd1;
        random_cycles = 100;

        if (FIFO_DEPTH < 3)
            $fatal(1, "FIFO_DEPTH must be at least 3 for partial-occupancy tests");

        seed_was_set = $value$plusargs("SEED=%d", random_state);
        if (!seed_was_set)
            random_state = 32'd1;
        initial_seed = random_state;
        seed_was_set = $value$plusargs("RANDOM_CYCLES=%d", random_cycles);
        if (!seed_was_set)
            random_cycles = 100;

        $display("INFO FIFO_DEPTH=%0d SEED=%0d RANDOM_CYCLES=%0d",
            FIFO_DEPTH, random_state, random_cycles);

        apply_reset("initial_reset");

        apply_cycle(1'b1, 1'b0, 8'h00, "single_write_zero");
        apply_cycle(1'b0, 1'b1, 8'h00, "single_read_zero");
        apply_cycle(1'b1, 1'b0, 8'hFF, "single_write_ones");
        apply_cycle(1'b0, 1'b1, 8'h00, "single_read_ones");

        apply_cycle(1'b1, 1'b0, 8'h11, "ordered_writes");
        apply_cycle(1'b1, 1'b0, 8'h22, "ordered_writes");
        apply_cycle(1'b1, 1'b0, 8'h33, "ordered_writes");
        apply_cycle(1'b0, 1'b1, 8'h00, "ordered_reads");
        apply_cycle(1'b0, 1'b1, 8'h00, "ordered_reads");
        apply_cycle(1'b0, 1'b1, 8'h00, "ordered_reads");

        for (iteration = 0; iteration < FIFO_DEPTH; iteration = iteration + 1)
            apply_cycle(1'b1, 1'b0, 8'h40 + iteration, "fill_to_full");
        apply_cycle(1'b1, 1'b0, 8'hEE, "write_rejected_when_full");
        for (iteration = 0; iteration < FIFO_DEPTH; iteration = iteration + 1)
            apply_cycle(1'b0, 1'b1, 8'h00, "drain_after_rejected_write");
        apply_cycle(1'b0, 1'b1, 8'h00, "read_rejected_when_empty");

        for (iteration = 0; iteration < FIFO_DEPTH + 2; iteration = iteration + 1) begin
            apply_cycle(1'b1, 1'b0, 8'h70 + iteration, "write_pointer_wrap");
            apply_cycle(1'b0, 1'b1, 8'h00, "read_pointer_wrap");
        end

        apply_cycle(1'b1, 1'b0, 8'hA1, "partial_simultaneous_setup");
        apply_cycle(1'b1, 1'b0, 8'hA2, "partial_simultaneous_setup");
        apply_cycle(1'b1, 1'b1, 8'hA3, "simultaneous_partially_occupied");
        apply_cycle(1'b0, 1'b1, 8'h00, "partial_simultaneous_drain");
        apply_cycle(1'b0, 1'b1, 8'h00, "partial_simultaneous_drain");

        apply_cycle(1'b1, 1'b1, 8'h00, "simultaneous_when_empty");
        apply_cycle(1'b0, 1'b1, 8'h00, "read_after_simultaneous_empty");

        for (iteration = 0; iteration < FIFO_DEPTH; iteration = iteration + 1)
            apply_cycle(1'b1, 1'b0, 8'h80 + iteration, "simultaneous_full_setup");
        apply_cycle(1'b1, 1'b1, 8'hFE, "simultaneous_when_full");
        for (iteration = 0; iteration < FIFO_DEPTH - 1; iteration = iteration + 1)
            apply_cycle(1'b0, 1'b1, 8'h00, "drain_after_simultaneous_full");

        apply_cycle(1'b1, 1'b0, 8'h5A, "reset_during_operation_setup");
        apply_cycle(1'b1, 1'b0, 8'hC3, "reset_during_operation_setup");
        apply_reset("reset_during_operation");
        apply_cycle(1'b1, 1'b0, 8'hFF, "post_reset_write");
        apply_cycle(1'b0, 1'b1, 8'h00, "post_reset_read");

        for (iteration = 0; iteration < random_cycles; iteration = iteration + 1) begin
            random_state = next_random(random_state);
            data_in = random_state[15:8];
            apply_cycle(random_state[0], random_state[1], data_in,
                "seeded_randomized_operations");
        end

        $display("PASS ALL FIFO TESTS cycles=%0d seed=%0d",
            cycle_number, initial_seed);
        $finish;
    end

endmodule