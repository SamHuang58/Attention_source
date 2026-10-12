`timescale 1ns/1ps
// v2 UQ1.4: one integer bit and four fractional bits; 1.0 is encoded as 16.
// Input is max_score - score, an unsigned integer. No 1/sqrt(d) scaling.
// Round 16*exp(-distance) to nearest; all integer distances >= 4 round to zero.
module exp_lut (
    input wire [18:0] distance,
    output reg [4:0] weight
);
    always @* begin
        case (distance)
            0: weight = 5'd16;
            1: weight = 5'd5;
            2: weight = 5'd2;
            3: weight = 5'd1;
            default: weight = 5'd0;
        endcase
    end
endmodule
