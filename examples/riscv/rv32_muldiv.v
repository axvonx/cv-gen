// RV32M as two named, purely combinational subcircuits. No signal is wider than
// 32 bits and every multiply is 16x16, so CircuitVerse computes each node exactly
// (its native multiplier loses low bits on 32x32 products).
//
// RV32_BEHAVIORAL_ARITHMETIC selects an equivalent behavioral body for compiled
// models (native Verilator, Super Turbo WASM): the structural divider costs a
// 32-stage evaluation every cycle there. Exported CircuitVerse projects keep the
// structural bodies; tests/test_doom_machine.py checks both against a reference.

// op is funct3[1:0]: 0 MUL, 1 MULH, 2 MULHSU, 3 MULHU.
module rv32_mul(input [31:0] a,b,input [1:0] op,output [31:0] value);
`ifdef RV32_BEHAVIORAL_ARITHMETIC
 wire [63:0] full=op==3 ? {32'b0,a}*{32'b0,b} :
                  op==2 ? $unsigned($signed({{32{a[31]}},a})*$signed({32'b0,b})) :
                  $unsigned($signed({{32{a[31]}},a})*$signed({{32{b[31]}},b}));
 assign value=op==0 ? full[31:0] : full[63:32];
`else
 wire [31:0] ll={16'b0,a[15:0]}*{16'b0,b[15:0]};
 wire [31:0] lh={16'b0,a[15:0]}*{16'b0,b[31:16]};
 wire [31:0] hl={16'b0,a[31:16]}*{16'b0,b[15:0]};
 wire [31:0] hh={16'b0,a[31:16]}*{16'b0,b[31:16]};
 wire [31:0] middle={16'b0,ll[31:16]}+{16'b0,lh[15:0]}+{16'b0,hl[15:0]};
 wire [31:0] low={middle[15:0],ll[15:0]};
 wire [31:0] high=hh+{16'b0,lh[31:16]}+{16'b0,hl[31:16]}+{16'b0,middle[31:16]};
 // Signed high words: subtract b when a is negative (MULH, MULHSU), a when b is (MULH).
 wire [31:0] fix_a=(op!=3 && a[31]) ? b : 32'b0;
 wire [31:0] fix_b=(op==1 && b[31]) ? a : 32'b0;
 assign value=op==0 ? low : high-fix_a-fix_b;
`endif
endmodule

// One restoring-division step (a separate module keeps each CircuitVerse scope small).
module rv32_div_stage(input [31:0] remainder,divisor,input next_bit,output take,output [31:0] next);
 wire [31:0] shifted={remainder[30:0],next_bit};
 assign take=remainder[31] || shifted>=divisor;
 assign next=take ? shifted-divisor : shifted;
endmodule

// op is funct3[1:0]: 0 DIV, 1 DIVU, 2 REM, 3 REMU. Division by zero gives an
// all-ones quotient and the dividend as remainder; -2^31/-1 gives -2^31 rem 0.
module rv32_div(input [31:0] a,b,input [1:0] op,output [31:0] value);
`ifdef RV32_BEHAVIORAL_ARITHMETIC
 wire overflow=!op[0] && a==32'h80000000 && b==32'hffffffff;
 wire [31:0] q=b==0 ? 32'hffffffff : overflow ? a :
               op[0] ? a/b : $unsigned($signed(a)/$signed(b));
 wire [31:0] r=b==0 ? a : overflow ? 32'b0 :
               op[0] ? a%b : $unsigned($signed(a)%$signed(b));
 assign value=op[1] ? r : q;
`else
 wire signed_op=!op[0];
 wire negative_a=signed_op && a[31], negative_b=signed_op && b[31];
 wire [31:0] dividend=negative_a ? 32'b0-a : a;
 wire [31:0] divisor=negative_b ? 32'b0-b : b;
 // Restoring division, one quotient bit per stage. The partial remainder stays
 // below the divisor, so when the shifted remainder's lost top bit is set it
 // exceeds the divisor and the 32-bit difference is exact.
 wire [31:0] remainder[0:32];
 wire [31:0] quotient;
 assign remainder[0]=32'b0;
 genvar i;
 generate for(i=0;i<32;i=i+1)begin:stage
  rv32_div_stage s(remainder[i],divisor,dividend[31-i],quotient[31-i],remainder[i+1]);
 end endgenerate
 wire [31:0] q=b==0 ? 32'hffffffff : (negative_a^negative_b) ? 32'b0-quotient : quotient;
 wire [31:0] r=negative_a ? 32'b0-remainder[32] : remainder[32];
 assign value=op[1] ? r : q;
`endif
endmodule

// M-extension result for an OP instruction with funct7=1.
module rv32_muldiv(input [31:0] a,b,input [2:0] f3,output [31:0] value);
 wire [31:0] product,division;
 rv32_mul multiplier(a,b,f3[1:0],product);
 rv32_div divider(a,b,f3[1:0],division);
 assign value=f3[2] ? division : product;
endmodule
