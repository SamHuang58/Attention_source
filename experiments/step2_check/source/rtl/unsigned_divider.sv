`timescale 1ns/1ps
// Restoring divider: W compute cycles, unsigned quotient truncated downward.
// Busy starts are ignored. A zero divisor returns zero and raises divide_by_zero.
module unsigned_divider #(parameter W = 36) (
    input wire clk, rst_n, start,
    input wire [W-1:0] numerator, denominator,
    output reg [W-1:0] quotient,
    output reg busy, done, divide_by_zero
);
    localparam CW = $clog2(W+1);
    reg [W-1:0] q_work, divisor;
    reg [W:0] remainder;
    reg [CW-1:0] count;
    wire [W:0] shifted = {remainder[W-1:0], q_work[W-1]};
    wire subtract = shifted >= {1'b0, divisor};
    // Shift instead of q_work[W-2:0]: the latter is an illegal slice at W=1.
    // The comparison bit becomes the newly computed quotient bit.
    wire [W-1:0] next_q = (q_work << 1) | {{(W-1){1'b0}}, subtract};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            quotient <= 0; busy <= 0; done <= 0; divide_by_zero <= 0;
            q_work <= 0; divisor <= 0; remainder <= 0; count <= 0;
        end else begin
            done <= 0;
            if (!busy) begin
                if (start) begin
                    divide_by_zero <= denominator == 0;
                    if (denominator == 0) begin quotient <= 0; done <= 1; end
                    else begin
                        busy <= 1; q_work <= numerator; divisor <= denominator;
                        remainder <= 0; count <= W;
                    end
                end
            end else begin
                remainder <= subtract ? shifted - {1'b0, divisor} : shifted;
                q_work <= next_q;
                count <= count - 1'b1;
                if (count == 1) begin quotient <= next_q; busy <= 0; done <= 1; end
            end
        end
    end
endmodule
