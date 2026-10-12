`timescale 1ns/1ps
module tb_divider;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0;
    reg [35:0] numerator=0,denominator=0;
    wire [35:0] quotient;
    wire busy,done,divide_by_zero;
    unsigned_divider dut(.*);
    reg [35:0] expect_q;
    reg [63:0] r=64'h3141592653589793;
    integer i,cycles;
    initial begin #1000000;$fatal(1,"divider timeout");end
    initial begin
        repeat(2)@(negedge clk);rst_n=1;
        for(i=0;i<1024;i=i+1) begin
            @(negedge clk);
            r=r^(r<<13);r=r^(r>>7);r=r^(r<<17);numerator=r[35:0];
            r=r^(r<<13);r=r^(r>>7);r=r^(r<<17);denominator=r[35:0];
            case(i)
                0:begin numerator=0;denominator=1;end
                1:begin numerator={36{1'b1}};denominator=1;end
                2:begin numerator=36'd34359738368;denominator=1048576;end
                3:begin numerator=99;denominator=0;end
                4:begin numerator=17;denominator=3;end
            endcase
            expect_q=denominator==0 ? 0 : numerator/denominator;
            start=1;@(posedge clk);#2;cycles=0;
            while(!done) begin
                @(negedge clk);start=1; // exercise busy starts
                @(posedge clk);#2;cycles=cycles+1;
            end
            if(quotient!==expect_q || divide_by_zero!==(denominator==0))$fatal(1,"divider mismatch i=%0d",i);
            if(denominator!=0 && cycles!=36)$fatal(1,"divider latency");
            @(negedge clk);start=0;
        end
        $display("DIVIDER PASS: 1024 cases; 36 cycles; divide-by-zero checked");$finish;
    end
endmodule
