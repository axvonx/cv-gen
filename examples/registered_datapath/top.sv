`include "offset.vh"
module top #(parameter WIDTH = 4) (
  input clk,
  input rst,
  input [WIDTH-1:0] a,
  input [WIDTH-1:0] b,
  output reg [WIDTH-1:0] q
);
  wire [WIDTH-1:0] next_value;
  add_offset #(.WIDTH(WIDTH)) u_add(.a(a), .b(b), .y(next_value));
  always @(posedge clk or posedge rst)
    if (rst) q <= '0;
    else q <= next_value;
endmodule
