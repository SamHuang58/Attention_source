`timescale 1ns/1ps
module tb_divider_exhaustive;
    parameter W=4;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0;
    reg [W-1:0] numerator=0,denominator=0;
    wire [W-1:0] quotient;
    wire busy,done,divide_by_zero;
    unsigned_divider #(.W(W)) dut(.*);
    reg [63:0] rng=64'h123456789abcdef;
    integer a,b,i,count=0,abort_at;
    task tick;begin @(posedge clk);#2;end endtask
    task check_division(input reg[W-1:0] num,den);
        reg[W-1:0] expected_q;
        integer c;
        begin
            expected_q=den==0 ? 0 : num/den;
            @(negedge clk);start=1;numerator=num;denominator=den;tick();
            if(den==0)begin
                if(done!==1 || busy!==0 || divide_by_zero!==1 || quotient!==0)$fatal(1,"W=%0d zero divisor",W);
            end else begin
                if(busy!==1 || done!==0 || divide_by_zero!==0)$fatal(1,"W=%0d launch",W);
                for(c=1;c<=W;c=c+1)begin
                    // Inputs must be captured on start, even when they change while busy.
                    @(negedge clk);start=1;numerator=~num;denominator=~den;tick();
                    if(busy!==(c<W) || done!==(c==W))$fatal(1,"W=%0d latency at %0d",W,c);
                    if(divide_by_zero!==0)$fatal(1,"W=%0d false divide-by-zero at %0d",W,c);
                end
                if(quotient!==expected_q)$fatal(1,"W=%0d num=%0d den=%0d actual=%0d expected=%0d",W,num,den,quotient,expected_q);
            end
            @(negedge clk);start=0;tick();
            if(done!==0 || busy!==0 || quotient!==expected_q)$fatal(1,"W=%0d completion/hold",W);
            if(divide_by_zero!==(den==0))$fatal(1,"W=%0d divide-by-zero hold",W);
            count=count+1;
        end
    endtask
    initial begin #20000000;$fatal(1,"divider exhaustive watchdog");end
    initial begin
        repeat(2)@(negedge clk);rst_n=1;
        if(W<=8)begin
            for(a=0;a<(1<<W);a=a+1)
                for(b=0;b<(1<<W);b=b+1)check_division(a,b);
        end else begin
            check_division(0,0);check_division(0,1);check_division({W{1'b1}},1);
            check_division({W{1'b1}},{W{1'b1}});
            for(i=0;i<W;i=i+1)begin
                check_division({W{1'b1}},{{(W-1){1'b0}},1'b1}<<i);
                check_division(({{(W-1){1'b0}},1'b1}<<i)-1,{{(W-1){1'b0}},1'b1}<<i);
            end
            for(i=0;i<2048;i=i+1)begin
                rng=rng^(rng<<13);rng=rng^(rng>>7);rng=rng^(rng<<17);numerator=rng[W-1:0];
                rng=rng^(rng<<13);rng=rng^(rng>>7);rng=rng^(rng<<17);denominator=rng[W-1:0];
                check_division(numerator,denominator);
            end
        end
        for(abort_at=0;abort_at<W;abort_at=abort_at+1)begin
            @(negedge clk);start=1;numerator={W{1'b1}};denominator=1;tick();
            repeat(abort_at)tick();
            @(negedge clk);start=0;rst_n=0;#1;
            if(busy!==0 || done!==0 || quotient!==0 || divide_by_zero!==0)$fatal(1,"W=%0d async reset",W);
            @(negedge clk);rst_n=1;
            repeat(W+1)begin tick();if(done!==0 || busy!==0)$fatal(1,"W=%0d stale completion",W);end
            check_division({W{1'b1}},1);
        end
        $display("DIVIDER EXHAUSTIVE PASS: W=%0d cases=%0d reset_positions=%0d",W,count,W);$finish;
    end
endmodule
