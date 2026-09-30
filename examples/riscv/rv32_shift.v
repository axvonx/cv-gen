// Mux/concatenation barrel shifter avoids native 32-bit signed JS >> behavior.
module rv32_shift(input [31:0] value,input [4:0] amount,input arithmetic,output [31:0] left,right);
 wire [31:0] l0=value,r0=value;
 wire fill=arithmetic && value[31];
 wire [31:0] l1=amount[0] ? {l0[30:0],1'b0} : l0;
 wire [31:0] r1=amount[0] ? {{1{fill}},r0[31:1]} : r0;
 wire [31:0] l2=amount[1] ? {l1[29:0],2'b0} : l1;
 wire [31:0] r2=amount[1] ? {{2{fill}},r1[31:2]} : r1;
 wire [31:0] l3=amount[2] ? {l2[27:0],4'b0} : l2;
 wire [31:0] r3=amount[2] ? {{4{fill}},r2[31:4]} : r2;
 wire [31:0] l4=amount[3] ? {l3[23:0],8'b0} : l3;
 wire [31:0] r4=amount[3] ? {{8{fill}},r3[31:8]} : r3;
 wire [31:0] l5=amount[4] ? {l4[15:0],16'b0} : l4;
 wire [31:0] r5=amount[4] ? {{16{fill}},r4[31:16]} : r4;
 assign left=l5;assign right=r5;
endmodule
