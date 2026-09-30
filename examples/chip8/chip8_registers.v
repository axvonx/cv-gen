module chip8_register(input clk,rst,enable,flag_enable,input [7:0] data,
 input flag,output reg [7:0] q);
 always @(posedge clk or posedge rst)
  if(rst)q<=0;else if(flag_enable)q<={7'b0,flag};else if(enable)q<=data;
endmodule
module chip8_registers(input clk,rst,enable,flag_enable,input [3:0] dest,x,y,
 input [7:0] data,input flag,output reg [7:0] a,b,
 output [7:0] v0,vf);
 wire [7:0] values[0:15];
 genvar g;
 generate for(g=0;g<16;g=g+1)begin:bank
  chip8_register r(clk,rst,enable && dest==g,flag_enable && g==15,data,flag,values[g]);
 end endgenerate
 always @* begin a=(x[3] ? (x[2] ? (x[1] ? (x[0] ? values[15] : values[14]) : (x[0] ? values[13] : values[12])) : (x[1] ? (x[0] ? values[11] : values[10]) : (x[0] ? values[9] : values[8]))) : (x[2] ? (x[1] ? (x[0] ? values[7] : values[6]) : (x[0] ? values[5] : values[4])) : (x[1] ? (x[0] ? values[3] : values[2]) : (x[0] ? values[1] : values[0]))));b=(y[3] ? (y[2] ? (y[1] ? (y[0] ? values[15] : values[14]) : (y[0] ? values[13] : values[12])) : (y[1] ? (y[0] ? values[11] : values[10]) : (y[0] ? values[9] : values[8]))) : (y[2] ? (y[1] ? (y[0] ? values[7] : values[6]) : (y[0] ? values[5] : values[4])) : (y[1] ? (y[0] ? values[3] : values[2]) : (y[0] ? values[1] : values[0]))));end
 assign v0=values[0];assign vf=values[15];
endmodule
module chip8_stack_word(input clk,rst,enable,input [11:0] data,output reg [11:0] q);
 always @(posedge clk or posedge rst)if(rst)q<=0;else if(enable)q<=data;
endmodule
module chip8_stack(input clk,rst,enable,input [3:0] address,input [11:0] data,output reg [11:0] q);
 wire [11:0] values[0:15];genvar g;
 generate for(g=0;g<16;g=g+1)begin:bank
  chip8_stack_word r(clk,rst,enable && address==g,data,values[g]);
 end endgenerate
 always @* q=(address[3] ? (address[2] ? (address[1] ? (address[0] ? values[15] : values[14]) : (address[0] ? values[13] : values[12])) : (address[1] ? (address[0] ? values[11] : values[10]) : (address[0] ? values[9] : values[8]))) : (address[2] ? (address[1] ? (address[0] ? values[7] : values[6]) : (address[0] ? values[5] : values[4])) : (address[1] ? (address[0] ? values[3] : values[2]) : (address[0] ? values[1] : values[0]))));
endmodule
