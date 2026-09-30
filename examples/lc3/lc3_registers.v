module lc3_register (
    input clk,
    rst,
    enable,
    input [15:0] data,
    output reg [15:0] q
);
  always @(posedge clk or posedge rst)
    if (rst) q <= 0;
    else if (enable) q <= data;
endmodule
module lc3_registers (
    input clk,
    rst,
    enable,
    input [2:0] dest,
    x,
    y,
    input [15:0] data,
    output reg [15:0] a,
    b,
    output [15:0] r0,
    r1,
    r2,
    r3,
    r6,
    r7
);
  wire [15:0] values[0:7];
  genvar g;
  generate
    for (g = 0; g < 8; g = g + 1) begin : bank
      lc3_register r (
          clk,
          rst,
          enable && dest == g,
          data,
          values[g]
      );
    end
  endgenerate
  always @* begin
    a=(x[2] ? (x[1] ? (x[0] ? values[7] : values[6]) : (x[0] ? values[5] : values[4])) : (x[1] ? (x[0] ? values[3] : values[2]) : (x[0] ? values[1] : values[0])));
    b=(y[2] ? (y[1] ? (y[0] ? values[7] : values[6]) : (y[0] ? values[5] : values[4])) : (y[1] ? (y[0] ? values[3] : values[2]) : (y[0] ? values[1] : values[0])));
  end
  assign r0 = values[0];
  assign r1 = values[1];
  assign r2 = values[2];
  assign r3 = values[3];
  assign r6 = values[6];
  assign r7 = values[7];
endmodule
