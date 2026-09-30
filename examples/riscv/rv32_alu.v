// RV32I integer operations; funct3 is shared by register and immediate forms.
module rv32_alu(input [31:0] a,b,input [2:0] op,input alternate,
 output reg [31:0] value,output less_signed,less_unsigned,equal);
 wire [31:0] left,right;
 rv32_shift shifter(a,b[4:0],alternate,left,right);
 assign less_signed = a[31]!=b[31] ? a[31] : a<b;
 assign less_unsigned = a<b;
 assign equal = a==b;
 always @* case(op)
  0: value=alternate ? a-b : a+b;
  1: value=left;
  2: value={31'b0,less_signed};
  3: value={31'b0,less_unsigned};
  4: value=a^b;
  5: value=right;
  6: value=a|b;
  7: value=a&b;
 endcase
endmodule
