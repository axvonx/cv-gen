`include "offset.vh"
module add_offset #(parameter WIDTH = 4) (
  input [WIDTH-1:0] a,
  input [WIDTH-1:0] b,
  output [WIDTH-1:0] y
);
`ifdef CVGEN_EXAMPLE
  assign y = a `CVGEN_ADD b;
`else
  assign y = a - b;
`endif
endmodule
