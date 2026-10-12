`timescale 1ns/1ps
// Port-only checker, shared by RTL and actual synthesized gate netlist.
// Drive on falling edges; sample after rising-edge nonblocking assignments.
module tb_netlist;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,start=0,q_valid=0,kv_valid=0;
    reg signed [7:0] q_in=0,k_in=0,v_in=0;
    wire data_ready,out_valid,done;
    wire signed [7:0] out_data;
    attention_ip dut(.*);
    integer fd,rc,n,i,kidx,dummy,got,waited,gap,stalls,results;
    integer q[0:3],ks[0:31],vs[0:31],expect_o[0:3],actual_o[0:3];
    integer max_stall=0,cycles=0,watchdog_cycles=2000000;
    reg [31:0] rng=32'h2468ace1;
    string vectors_path="build/vectors.txt",results_path="results";
    always @(posedge clk) begin
        cycles=cycles+1;
        if(cycles>watchdog_cycles)$fatal(1,"netlist watchdog case=%0d",kidx);
        #1;
        if(rst_n) begin
            if((^{data_ready,out_valid,done})===1'bx)$fatal(1,"netlist unknown control");
            if(done && !out_valid)$fatal(1,"netlist done without valid");
            if(out_valid && (^out_data)===1'bx)$fatal(1,"netlist unknown output");
        end
    end
    task tick; begin @(posedge clk);#2;end endtask
    task randomize;
        begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);end
    endtask
    task check_load;
        begin
            if(data_ready!==1 || out_valid!==0 || done!==0)$fatal(1,"netlist load protocol");
        end
    endtask
    initial begin
        dummy=$value$plusargs("VECTORS=%s",vectors_path);
        dummy=$value$plusargs("RESULTS=%s",results_path);
        dummy=$value$plusargs("SEED=%d",rng);
        dummy=$value$plusargs("MAX_STALL=%d",max_stall);
        dummy=$value$plusargs("WATCHDOG_CYCLES=%d",watchdog_cycles);
        if(rng==0 || max_stall<0 || max_stall>1000)$fatal(1,"invalid netlist configuration");
        fd=$fopen(vectors_path,"r");if(!fd)$fatal(1,"missing vectors");
        results=$fopen($sformatf("%s/netlist_results.csv",results_path),"w");
        if(!results)$fatal(1,"cannot open netlist results");
        $fwrite(results,"case,cycles,stalls,o0,o1,o2,o3\n");
        rc=$fscanf(fd,"%d",n);if(rc!=1 || n<1)$fatal(1,"invalid count");
        repeat(3)@(negedge clk);rst_n=1;
        for(kidx=0;kidx<n;kidx=kidx+1) begin
            for(i=0;i<4;i=i+1)begin rc=$fscanf(fd,"%d",q[i]);if(rc!=1)$fatal(1,"truncated Q");end
            for(i=0;i<32;i=i+1)begin rc=$fscanf(fd,"%d",ks[i]);if(rc!=1)$fatal(1,"truncated K");end
            for(i=0;i<32;i=i+1)begin rc=$fscanf(fd,"%d",vs[i]);if(rc!=1)$fatal(1,"truncated V");end
            for(i=0;i<21;i=i+1)begin rc=$fscanf(fd,"%d",dummy);if(rc!=1)$fatal(1,"truncated intermediates");end
            for(i=0;i<4;i=i+1)begin rc=$fscanf(fd,"%d",expect_o[i]);if(rc!=1)$fatal(1,"truncated output");end
            // Accept next start at the first edge after the previous final output.
            @(negedge clk);start=1;q_valid=1;kv_valid=1;q_in=99;tick();check_load();
            stalls=0;
            for(i=0;i<4;i=i+1)begin
                randomize();gap=kidx==0 ? 0 : rng%(max_stall+1);
                repeat(gap)begin
                    @(negedge clk);start=1;q_valid=0;kv_valid=1;q_in=-100;
                    check_load();tick();check_load();stalls=stalls+1;
                end
                @(negedge clk);start=1;q_valid=1;kv_valid=1;q_in=q[i];
                check_load();tick();
            end
            for(i=0;i<32;i=i+1)begin
                randomize();gap=kidx==0 ? 0 : rng%(max_stall+1);
                repeat(gap)begin
                    @(negedge clk);start=1;kv_valid=0;q_valid=1;k_in=91;v_in=-67;
                    check_load();tick();check_load();stalls=stalls+1;
                end
                @(negedge clk);start=1;q_valid=1;kv_valid=1;k_in=ks[i];v_in=vs[i];
                check_load();tick();
            end
            if(data_ready!==0 || out_valid!==0 || done!==0)$fatal(1,"netlist final KV handshake");
            got=0;
            for(waited=1;waited<=228;waited=waited+1)begin
                @(negedge clk);start=(waited%7==0);q_valid=1;kv_valid=1;q_in=-100;k_in=85;v_in=-37;
                tick();
                if(data_ready!==0)$fatal(1,"netlist ready during compute/output");
                if(out_valid!==(waited>=225))$fatal(1,"netlist early/missing/nonconsecutive output");
                if(done!==(waited==228))$fatal(1,"netlist done alignment");
                if(out_valid)begin
                    actual_o[got]=$signed(out_data);
                    if(out_data!==expect_o[got])$fatal(1,"netlist mismatch case=%0d dim=%0d actual=%0d expected=%0d",kidx,got,out_data,expect_o[got]);
                    got=got+1;
                end
            end
            $fwrite(results,"%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",kidx,264+stalls,stalls,actual_o[0],actual_o[1],actual_o[2],actual_o[3]);
        end
        @(negedge clk);start=0;q_valid=1;kv_valid=1;
        repeat(4)begin tick();if(out_valid!==0 || done!==0 || data_ready!==0)$fatal(1,"netlist idle traffic");end
        $fclose(fd);$fclose(results);
        $display("NETLIST PASS: %0d cases, %0d outputs, base latency=264; stalls and earliest restart checked; functional zero-delay simulation",n,4*n);
        $finish;
    end
endmodule
