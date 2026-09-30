module chip8_alu (
    input [3:0] op,
    input [7:0] a,
    b,
    output reg [7:0] value,
    output reg flag,
    output reg flag_write,
    output reg valid
);
  wire [8:0] sum = {1'b0, a} + {1'b0, b};
  always @* begin
    value = a;
    flag = 0;
    flag_write = 0;
    valid = 1;
    case (op)
      0: value = b;
      1: value = a | b;
      2: value = a & b;
      3: value = a ^ b;
      4: begin
        value = sum[7:0];
        flag = sum[8];
        flag_write = 1;
      end
      5: begin
        value = a - b;
        flag = a >= b;
        flag_write = 1;
      end
      6: begin
        value = {1'b0, b[7:1]};
        flag = b[0];
        flag_write = 1;
      end
      7: begin
        value = b - a;
        flag = b >= a;
        flag_write = 1;
      end
      14: begin
        value = {b[6:0], 1'b0};
        flag = b[7];
        flag_write = 1;
      end
      default: valid = 0;
    endcase
  end
endmodule
