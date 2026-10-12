`timescale 1ns/1ps
module tb_attention;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, start=0, q_valid=0, kv_valid=0;
    reg signed [7:0] q_in=0,k_in=0,v_in=0;
    wire data_ready,out_valid,done;
    wire signed [7:0] out_data;
    attention_ip dut(.*);
    integer cycle=0, fd, rc, ncases, test_id=-1, i,j,dummy;
    integer q[0:3],k[0:31],v[0:31],es[0:7],ew[0:7],el,ea[0:3],eo[0:3];
    integer trace, results, got, start_cycle, stalls, last_output, gap, target;
    reg [31:0] rng=32'h13579bdf;
    integer trace_limit=1;
    reg demo=0;
    string vectors_path="build/vectors.txt", results_path="results";
    integer max_stall=2, watchdog_cycles=2000000;
    integer actual_o[0:3], state_hits[0:8], distance_hits[0:13];
    integer positive_outputs=0, negative_outputs=0, zero_outputs=0;
    integer stalled_q=0, stalled_kv=0, busy_start_hits=0, coverage_fd;
    integer before_state, before_dim, before_token, before_address;
    reg signed [7:0] before_q, before_k, before_v;
    reg before_q_valid, before_kv_valid;
    wire signed [17:0] debug_score=dut.scores[dut.token];
    wire [4:0] debug_weight=dut.weights[dut.token];
    wire signed [15:0] debug_acc0=dut.acc[0];
    always @(posedge clk) begin
        cycle=cycle+1;
        if(cycle>watchdog_cycles) $fatal(1,"WATCHDOG case=%0d state=%0d",test_id,dut.state);
        before_state=dut.state;before_dim=dut.dim;before_token=dut.token;
        before_q_valid=q_valid;before_kv_valid=kv_valid;
        before_address={dut.token,dut.dim};
        before_q=dut.q_mem[dut.dim];before_k=dut.k_mem[before_address];before_v=dut.v_mem[before_address];
        #1;
        if(rst_n) begin
            if ((^{data_ready,out_valid,done}) === 1'bx) $fatal(1,"unknown control output");
            if (out_valid && (^out_data) === 1'bx) $fatal(1,"unknown valid data");
            if(data_ready !== (dut.state==1 || dut.state==2)) $fatal(1,"ready/state mismatch");
            if(done && !out_valid) $fatal(1,"done without output");
            if(out_valid !== (before_state==8)) $fatal(1,"early/missing output");
            if(dut.state>8 || (^dut.state)===1'bx) $fatal(1,"illegal state");
            state_hits[dut.state]=state_hits[dut.state]+1;
            if(start && before_state!=0) busy_start_hits=busy_start_hits+1;
            if((before_state==1 && !before_q_valid) || (before_state==2 && !before_kv_valid)) begin
                if(dut.state!==before_state || dut.dim!==before_dim || dut.token!==before_token)
                    $fatal(1,"load counters advanced without handshake");
                if(before_state==1) stalled_q=stalled_q+1;
                else stalled_kv=stalled_kv+1;
            end
            // Check every received element immediately; also detect writes during a pause.
            if(before_state==1) begin
                if(before_q_valid && dut.q_mem[before_dim] !== q_in)
                    $fatal(1,"Q data capture cycle=%0d dim=%0d",cycle,before_dim);
                if(!before_q_valid && dut.q_mem[before_dim] !== before_q)
                    $fatal(1,"Q changed during pause cycle=%0d dim=%0d",cycle,before_dim);
            end
            if(before_state==2) begin
                if(before_kv_valid && (dut.k_mem[before_address] !== k_in || dut.v_mem[before_address] !== v_in))
                    $fatal(1,"KV data capture cycle=%0d address=%0d",cycle,before_address);
                if(!before_kv_valid && (dut.k_mem[before_address] !== before_k || dut.v_mem[before_address] !== before_v))
                    $fatal(1,"KV changed during pause cycle=%0d address=%0d",cycle,before_address);
            end
            if(dut.state>=5 && (dut.weight_sum<16 || dut.weight_sum>128))
                $fatal(1,"normalization denominator outside proven bounds");
        end
        if(trace && test_id>=0 && test_id<trace_limit) begin
            $fwrite(trace,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",test_id,cycle,rst_n,start,q_valid,kv_valid,data_ready,dut.state,dut.token,dut.dim,dut.max_score,dut.weight_sum,dut.acc[0],dut.acc[1],dut.acc[2],dut.acc[3],out_valid,out_data,done);
            $fwrite(trace,",%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",before_state,before_dim,before_token,q_in,k_in,v_in,$time);
        end
    end
    task tick; begin @(posedge clk); #2; end endtask
    task randomize; begin rng=(rng<<13)^rng; rng=(rng>>17)^rng; rng=(rng<<5)^rng; end endtask
    task reset_dut;
        begin
            @(negedge clk); rst_n=0;start=0;q_valid=0;kv_valid=0;
            #1;if(out_valid!==0 || done!==0 || data_ready!==0) $fatal(1,"asynchronous reset response");
            tick(); if(out_valid!==0 || done!==0 || data_ready!==0) $fatal(1,"reset protocol");
            @(negedge clk);rst_n=1;tick();
        end
    endtask
    task launch;
        begin @(negedge clk); start=1;q_valid=1;kv_valid=1;q_in=99;tick();
            start_cycle=cycle;
            if(dut.state!==1 || dut.dim!==0) $fatal(1,"start cycle accepted data");
        end
    endtask
    task run_case;
        begin
            launch(); stalls=0;
            for(i=0;i<4;i=i+1) begin
                randomize();gap=test_id==0 ? 0 : (demo ? (i==1 ? 3 : 0) : rng%(max_stall+1));
                repeat(gap) begin @(negedge clk);q_valid=0;kv_valid=!demo;start=!demo;tick();stalls=stalls+1;end
                @(negedge clk);q_valid=1;kv_valid=!demo;q_in=q[i];start=!demo;tick();
            end
            for(i=0;i<32;i=i+1) begin
                randomize();gap=test_id==0 ? 0 : (demo ? (i==5 ? 3 : 0) : rng%(max_stall+1));
                repeat(gap) begin @(negedge clk);kv_valid=0;q_valid=!demo;start=!demo;tick();stalls=stalls+1;end
                @(negedge clk);kv_valid=1;q_valid=!demo;k_in=k[i];v_in=v[i];start=!demo;tick();
            end
            @(negedge clk);kv_valid=0;q_valid=0;start=0;
            got=0;last_output=-1;
            while(got<4) begin
                // Invalid input traffic and busy start must not affect computation.
                start=!demo && (cycle%7==0);q_valid=!demo;kv_valid=!demo;q_in=-100;k_in=85;v_in=-37;
                tick();
                if(out_valid) begin
                    if(out_data !== eo[got]) $fatal(1,"output case=%0d dim=%0d got=%0d exp=%0d",test_id,got,out_data,eo[got]);
                    actual_o[got]=$signed(out_data);
                    if(out_data>0) positive_outputs=positive_outputs+1;
                    else if(out_data<0) negative_outputs=negative_outputs+1;
                    else zero_outputs=zero_outputs+1;
                    if(got>0 && cycle!=last_output+1) $fatal(1,"nonconsecutive outputs");
                    if(done !== (got==3)) $fatal(1,"done alignment");
                    last_output=cycle;got=got+1;
                end
                @(negedge clk);
            end
            start=0;q_valid=0;kv_valid=0;
            if(cycle-start_cycle != 264+stalls) $fatal(1,"latency: got=%0d expected=%0d",cycle-start_cycle,264+stalls);
            for(j=0;j<8;j=j+1) begin
                if(dut.scores[j] !== es[j]) $fatal(1,"score case=%0d j=%0d got=%0d expected=%0d",test_id,j,dut.scores[j],es[j]);
                if(dut.weights[j] !== ew[j]) $fatal(1,"weight case=%0d j=%0d got=%0d expected=%0d",test_id,j,dut.weights[j],ew[j]);
                dummy=$signed(dut.max_score)-$signed(dut.scores[j]);
                if(dummy<0 || dummy>130560) $fatal(1,"score distance bounds");
                if(dummy>12) dummy=13;
                distance_hits[dummy]=distance_hits[dummy]+1;
            end
            if(dut.weight_sum !== el) $fatal(1,"L mismatch");
            for(j=0;j<4;j=j+1) if(dut.acc[j] !== ea[j]) $fatal(1,"ACC mismatch");
            $fwrite(results,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",test_id,cycle-start_cycle,stalls,dut.weight_sum,actual_o[0],actual_o[1],actual_o[2],actual_o[3]);
            tick(); if(done || out_valid || dut.state!=0) $fatal(1,"idle after output");
        end
    endtask
    initial begin
        demo=$test$plusargs("DEMO");
        dummy=$value$plusargs("TRACE_LIMIT=%d",trace_limit);
        dummy=$value$plusargs("VECTORS=%s",vectors_path);
        dummy=$value$plusargs("RESULTS=%s",results_path);
        dummy=$value$plusargs("SEED=%d",rng);
        dummy=$value$plusargs("MAX_STALL=%d",max_stall);
        dummy=$value$plusargs("WATCHDOG_CYCLES=%d",watchdog_cycles);
        if(rng==0 || max_stall<0 || max_stall>1000 || watchdog_cycles<1) $fatal(1,"invalid test configuration");
        for(i=0;i<9;i=i+1)state_hits[i]=0;
        for(i=0;i<14;i=i+1)distance_hits[i]=0;
        if(!$test$plusargs("NO_WAVE")) begin
            $dumpfile($sformatf("%s/attention.vcd",results_path));$dumpvars(0,tb_attention);
        end
        fd=$fopen(vectors_path,"r");if(!fd)$fatal(1,"missing vectors");
        trace=$fopen($sformatf("%s/cycle_trace.csv",results_path),"w");
        results=$fopen($sformatf("%s/rtl_results.csv",results_path),"w");
        if(!trace || !results)$fatal(1,"cannot open outputs");
        $fwrite(trace,"case,cycle,rst_n,start,q_valid,kv_valid,ready,state,token,dim,max_score,L,acc0,acc1,acc2,acc3,out_valid,out_data,done,before_state,before_dim,before_token,q_in,k_in,v_in,time_ns\n");
        $fwrite(results,"case,cycles,stalls,L,o0,o1,o2,o3\n");
        reset_dut();
        if(!demo) begin
        // Abort each active state, including division and output, then recover.
        for(target=1;target<=8;target=target+1) begin
            launch();
            while(dut.state!=target) begin
                @(negedge clk);q_valid=1;kv_valid=1;q_in=1;k_in=1;v_in=2;tick();
            end
            reset_dut();
            repeat(4) begin tick();if(out_valid||done)$fatal(1,"stale output after abort");end
        end
        // Also abort after each incomplete output prefix, not just entry to OUTPUT.
        for(target=1;target<=3;target=target+1) begin
            launch();
            while(dut.state!=8) begin
                @(negedge clk);q_valid=1;kv_valid=1;q_in=1;k_in=1;v_in=2;tick();
            end
            repeat(target)tick();
            reset_dut();
            repeat(4)begin tick();if(out_valid||done)$fatal(1,"stale output after partial output reset");end
        end
        end
        rc=$fscanf(fd,"%d",ncases);if(rc!=1 || ncases<1)$fatal(1,"invalid case count");
        for(test_id=0;test_id<ncases;test_id=test_id+1) begin
            for(i=0;i<4;i=i+1) begin rc=$fscanf(fd,"%d",q[i]);if(rc!=1)$fatal;end
            for(i=0;i<32;i=i+1) begin rc=$fscanf(fd,"%d",k[i]);if(rc!=1)$fatal;end
            for(i=0;i<32;i=i+1) begin rc=$fscanf(fd,"%d",v[i]);if(rc!=1)$fatal;end
            for(i=0;i<8;i=i+1) begin rc=$fscanf(fd,"%d",es[i]);if(rc!=1)$fatal;end
            for(i=0;i<8;i=i+1) begin rc=$fscanf(fd,"%d",ew[i]);if(rc!=1)$fatal;end
            rc=$fscanf(fd,"%d",el);if(rc!=1)$fatal;
            for(i=0;i<4;i=i+1) begin rc=$fscanf(fd,"%d",ea[i]);if(rc!=1)$fatal;end
            for(i=0;i<4;i=i+1) begin rc=$fscanf(fd,"%d",eo[i]);if(rc!=1)$fatal;end
            run_case();
            if(test_id==trace_limit-1 && !$test$plusargs("NO_WAVE")) $dumpoff;
        end
        coverage_fd=$fopen($sformatf("%s/functional_coverage.json",results_path),"w");
        if(!coverage_fd)$fatal(1,"cannot save coverage");
        $fwrite(coverage_fd,"{\"state_cycles\":[");
        for(i=0;i<9;i=i+1)$fwrite(coverage_fd,"%0d%s",state_hits[i],i==8 ? "" : ",");
        $fwrite(coverage_fd,"],\"distance_bins_0_to_12_and_tail\":[");
        for(i=0;i<14;i=i+1)$fwrite(coverage_fd,"%0d%s",distance_hits[i],i==13 ? "" : ",");
        $fwrite(coverage_fd,"],\"positive_outputs\":%0d,\"negative_outputs\":%0d,\"zero_outputs\":%0d,\"q_stall_cycles\":%0d,\"kv_stall_cycles\":%0d,\"busy_start_cycles\":%0d,\"reset_states_checked\":8,\"partial_output_resets_checked\":3}\n",positive_outputs,negative_outputs,zero_outputs,stalled_q,stalled_kv,busy_start_hits);
        $fclose(coverage_fd);
        $fclose(fd);$fclose(trace);$fclose(results);
        $display("ATTENTION PASS: %0d cases, %0d outputs, Score/Weight/L/ACC exact; 8 reset states; base latency=264",ncases,ncases*4);
        $finish;
    end
endmodule
