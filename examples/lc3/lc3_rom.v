module lc3_rom (
    input [15:0] address,
    output reg [15:0] data,
    output reg valid
);
  always @* begin
    data  = 0;
    valid = 1;
    case (address)
      16'h3000: data = 16'h5020;
      16'h3001: data = 16'h1023;
      16'h3002: data = 16'h1225;
      16'h3003: data = 16'h320c;
      16'h3004: data = 16'h240b;
      16'h3005: data = 16'h96bf;
      16'h3006: data = 16'h16e1;
      16'h3007: data = 16'h0801;
      16'h3008: data = 16'h14a1;
      16'h3009: data = 16'h4802;
      16'h300a: data = 16'hf025;
      16'h300b: data = 16'h0fff;
      16'h300c: data = 16'h14a1;
      16'h300d: data = 16'hc1c0;
      16'h0025: data = 16'h3100;
      16'h3100: data = 16'h5020;
      16'h3101: data = 16'hb001;
      16'h3102: data = 16'hc1c0;
      16'h3103: data = 16'hfffe;
      default:  valid = 0;
    endcase
  end
endmodule
