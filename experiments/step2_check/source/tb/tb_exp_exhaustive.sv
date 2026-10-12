`timescale 1ns/1ps
module tb_exp_exhaustive;
    // Start uninitialized so assigning address zero triggers the combinational DUT.
    reg [18:0] distance;
    wire [4:0] weight;
    integer i,fd,rc,expected[0:3],previous=16;
    string expected_path;
    exp_lut dut(.*);
    initial begin
        if(!$value$plusargs("EXPECTED=%s",expected_path))$fatal(1,"missing independent LUT reference");
        fd=$fopen(expected_path,"r");if(!fd)$fatal(1,"missing LUT file");
        for(i=0;i<4;i=i+1)begin rc=$fscanf(fd,"%d",expected[i]);if(rc!=1)$fatal(1,"truncated LUT");end
        $fclose(fd);
        for(i=0;i<524288;i=i+1)begin
            distance=i;#1;
            if(weight!==(i<=3 ? expected[i] : 0))$fatal(1,"LUT address=%0d actual=%0d",i,weight);
            if(weight>previous)$fatal(1,"LUT is not monotone");
            previous=weight;
        end
        $display("LUT PASS: all 524288 input addresses; high-precision reference and monotonicity");$finish;
    end
endmodule
