module rv32_register(input clk,rst,enable,input [31:0] data,output reg [31:0] q);
 always @(posedge clk or posedge rst)if(rst)q<=0;else if(enable)q<=data;
endmodule
module rv32_registers(input clk,rst,enable,input [4:0] dest,x,y,
 input [31:0] data,output [31:0] a,b,a0,sp);
 wire [31:0] values[0:31];
 assign values[0]=0;
 genvar g;
 generate for(g=1;g<32;g=g+1)begin:bank
  rv32_register r(clk,rst,enable && dest==g,data,values[g]);
 end endgenerate
 assign a=(x[4] ? (x[3] ? (x[2] ? (x[1] ? (x[0] ? values[31] : values[30]) : (x[0] ? values[29] : values[28])) : (x[1] ? (x[0] ? values[27] : values[26]) : (x[0] ? values[25] : values[24]))) : (x[2] ? (x[1] ? (x[0] ? values[23] : values[22]) : (x[0] ? values[21] : values[20])) : (x[1] ? (x[0] ? values[19] : values[18]) : (x[0] ? values[17] : values[16])))) : (x[3] ? (x[2] ? (x[1] ? (x[0] ? values[15] : values[14]) : (x[0] ? values[13] : values[12])) : (x[1] ? (x[0] ? values[11] : values[10]) : (x[0] ? values[9] : values[8]))) : (x[2] ? (x[1] ? (x[0] ? values[7] : values[6]) : (x[0] ? values[5] : values[4])) : (x[1] ? (x[0] ? values[3] : values[2]) : (x[0] ? values[1] : values[0])))));
 assign b=(y[4] ? (y[3] ? (y[2] ? (y[1] ? (y[0] ? values[31] : values[30]) : (y[0] ? values[29] : values[28])) : (y[1] ? (y[0] ? values[27] : values[26]) : (y[0] ? values[25] : values[24]))) : (y[2] ? (y[1] ? (y[0] ? values[23] : values[22]) : (y[0] ? values[21] : values[20])) : (y[1] ? (y[0] ? values[19] : values[18]) : (y[0] ? values[17] : values[16])))) : (y[3] ? (y[2] ? (y[1] ? (y[0] ? values[15] : values[14]) : (y[0] ? values[13] : values[12])) : (y[1] ? (y[0] ? values[11] : values[10]) : (y[0] ? values[9] : values[8]))) : (y[2] ? (y[1] ? (y[0] ? values[7] : values[6]) : (y[0] ? values[5] : values[4])) : (y[1] ? (y[0] ? values[3] : values[2]) : (y[0] ? values[1] : values[0])))));
 assign a0=values[10];
 assign sp=values[2];
endmodule
