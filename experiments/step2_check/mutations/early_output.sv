`timescale 1ns/1ps
// Fixed baseline: batch=head=1, S=8, d=4. Data sampled only in its load state.
// start accepted only in IDLE; start cycle does not accept input.
// Four consecutive signed int8 outputs (nearest, ties away from zero), done coincides with the fourth output.
module attention_ip (
    input wire clk, rst_n, start,
    input wire signed [7:0] q_in, k_in, v_in,
    input wire q_valid, kv_valid,
    output wire data_ready,
    output reg signed [7:0] out_data,
    output reg out_valid, done
);
    localparam IDLE=0, LOAD_Q=1, LOAD_KV=2, DOT=3, EXP=4,
               UPDATE=5, NORM_START=6, NORM_WAIT=7, OUTPUT=8;
    reg [3:0] state;
    reg [2:0] token;
    reg [1:0] dim;
    reg signed [7:0] q_mem[0:3], k_mem[0:31], v_mem[0:31];
    reg signed [17:0] scores[0:7];
    reg [4:0] weights[0:7];
    reg signed [15:0] acc[0:3];
    reg signed [7:0] output_mem[0:3];
    reg signed [17:0] dot_acc, max_score;
    reg [7:0] weight_sum;
    wire [4:0] address = {token, dim};
    wire signed [15:0] dot_product = q_mem[dim] * k_mem[address];
    wire signed [17:0] dot_next = dot_acc + {{2{dot_product[15]}}, dot_product};
    wire signed [18:0] max_ext = {max_score[17], max_score};
    wire signed [18:0] score_ext = {scores[token][17], scores[token]};
    wire [18:0] distance = max_ext - score_ext;
    wire [4:0] lut_weight;
    exp_lut exp_table(.distance(distance), .weight(lut_weight));
    wire signed [5:0] positive_weight = {1'b0, weights[token]};
    wire signed [13:0] weighted_value = positive_weight * v_mem[address];
    wire signed [35:0] acc_extended = {{20{acc[dim][15]}}, acc[dim]};
    wire [35:0] magnitude = acc[dim][15] ? -acc_extended : acc_extended;
    // Integer nearest rounding: floor((abs(ACC) + floor(L/2))/L), then restore sign.
    // Weight and ACC share four fractional bits, which cancel in ACC/L.
    wire [35:0] divisor = {28'd0, weight_sum};
    wire [35:0] dividend = magnitude + (divisor >> 1);
    wire [35:0] quotient;
    wire divider_busy, divider_done, divide_by_zero;
    reg norm_negative;
    unsigned_divider #(.W(36)) norm_divider (
        .clk(clk), .rst_n(rst_n), .start(state == NORM_START),
        .numerator(dividend), .denominator(divisor), .quotient(quotient),
        .busy(divider_busy), .done(divider_done), .divide_by_zero(divide_by_zero)
    );
    assign data_ready = (state == LOAD_Q) || (state == LOAD_KV);
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; token <= 0; dim <= 0; out_data <= 0;
            out_valid <= 0; done <= 0; dot_acc <= 0;
            max_score <= -18'sd131072; weight_sum <= 0; norm_negative <= 0;
            // Data buffers need no reset: every used word is loaded before compute.
            for (i=0; i<4; i=i+1) acc[i] <= 0;
        end else begin
            out_valid <= 0; done <= 0;
            case (state)
                IDLE: if (start) begin
                    state <= LOAD_Q; dim <= 0; token <= 0; dot_acc <= 0;
                    max_score <= -18'sd131072; weight_sum <= 0;
                    for (i=0; i<4; i=i+1) acc[i] <= 0;
                end
                LOAD_Q: if (q_valid) begin
                    q_mem[dim] <= q_in;
                    if (dim == 3) begin dim <= 0; state <= LOAD_KV; end
                    else dim <= dim + 1'b1;
                end
                LOAD_KV: if (kv_valid) begin
                    k_mem[address] <= k_in; v_mem[address] <= v_in;
                    if (dim == 3) begin
                        dim <= 0;
                        if (token == 7) begin token <= 0; state <= DOT; out_valid <= 1; out_data <= 123; end
                        else token <= token + 1'b1;
                    end else dim <= dim + 1'b1;
                end
                DOT: begin
                    if (dim == 3) begin
                        scores[token] <= dot_next;
                        if (dot_next > max_score) max_score <= dot_next;
                        dot_acc <= 0; dim <= 0;
                        if (token == 7) begin token <= 0; state <= EXP; end
                        else token <= token + 1'b1;
                    end else begin dot_acc <= dot_next; dim <= dim + 1'b1; end
                end
                EXP: begin
                    weights[token] <= lut_weight;
                    weight_sum <= weight_sum + {3'd0, lut_weight};
                    if (token == 7) begin token <= 0; dim <= 0; state <= UPDATE; end
                    else token <= token + 1'b1;
                end
                UPDATE: begin
                    acc[dim] <= acc[dim] + {{2{weighted_value[13]}}, weighted_value};
                    if (dim == 3) begin
                        dim <= 0;
                        if (token == 7) begin token <= 0; state <= NORM_START; end
                        else token <= token + 1'b1;
                    end else dim <= dim + 1'b1;
                end
                NORM_START: begin norm_negative <= acc[dim][15]; state <= NORM_WAIT; end
                NORM_WAIT: if (divider_done) begin
                    if (divide_by_zero) output_mem[dim] <= 0; // unreachable for a valid transaction
                    else if (norm_negative)
                        output_mem[dim] <= quotient >= 36'd128 ? 8'sh80 : -$signed(quotient[7:0]);
                    else output_mem[dim] <= quotient > 36'd127 ? 8'sd127 : $signed(quotient[7:0]);
                    if (dim == 3) begin dim <= 0; state <= OUTPUT; end
                    else begin dim <= dim + 1'b1; state <= NORM_START; end
                end
                OUTPUT: begin
                    out_data <= output_mem[dim]; out_valid <= 1;
                    if (dim == 3) begin done <= 1; dim <= 0; state <= IDLE; end
                    else dim <= dim + 1'b1;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
