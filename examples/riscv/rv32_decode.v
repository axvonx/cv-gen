module rv32_decode(input [31:0] instruction,a,b,pc,
 output reg [31:0] value,next_pc,address,
 output reg write_register,load,store,illegal,
 output [2:0] size);
 wire [6:0] opcode=instruction[6:0],f7=instruction[31:25];
 wire [2:0] f3=instruction[14:12];
 wire [31:0] imm_i={{20{instruction[31]}},instruction[31:20]};
 wire [31:0] imm_s={{20{instruction[31]}},instruction[31:25],instruction[11:7]};
 wire [31:0] imm_b={{19{instruction[31]}},instruction[31],instruction[7],instruction[30:25],instruction[11:8],1'b0};
 wire [31:0] imm_j={{11{instruction[31]}},instruction[31],instruction[19:12],instruction[20],instruction[30:21],1'b0};
 wire [31:0] imm_u={instruction[31:12],12'b0};
 wire [31:0] alu_b=opcode==7'h13 ? imm_i : b;
 wire [31:0] alu_value;
 wire lt,ltu,eq;
 wire alternate=instruction[30] && (opcode==7'h33 || f3==5);
 rv32_alu alu(a,alu_b,f3,alternate,alu_value,lt,ltu,eq);
 reg take_branch;
 assign size=f3;
 always @* begin
  case(f3)
   0:take_branch=eq; 1:take_branch=!eq;
   4:take_branch=lt; 5:take_branch=!lt;
   6:take_branch=ltu; 7:take_branch=!ltu;
   default:take_branch=0;
  endcase
  value=alu_value;next_pc=pc+4;address=a+imm_i;
  write_register=0;load=0;store=0;illegal=0;
  case(opcode)
   7'h37:begin value=imm_u;write_register=1;end
   7'h17:begin value=pc+imm_u;write_register=1;end
   7'h6f:begin value=pc+4;next_pc=pc+imm_j;write_register=1;end
   7'h67:begin value=pc+4;next_pc=(a+imm_i)&32'hfffffffe;write_register=1;illegal=f3!=0;end
   7'h63:begin if(take_branch)next_pc=pc+imm_b;illegal=f3==2 || f3==3;end
   7'h13:begin
    write_register=1;
    if(f3==1)illegal=f7!=0;
    if(f3==5)illegal=f7!=0 && f7!=7'h20;
   end
   7'h33:begin
    write_register=1;
    illegal=f7!=0 && !(f7==7'h20 && (f3==0 || f3==5));
   end
   7'h03:begin load=1;illegal=!(f3==0 || f3==1 || f3==2 || f3==4 || f3==5);end
   7'h23:begin store=1;address=a+imm_s;illegal=f3>2;end
   7'h0f:illegal=f3!=0; // FENCE is a NOP on this in-order single-port machine.
   default:illegal=1; // SYSTEM instructions stop with a fault; no trap handler/CSRs.
  endcase
  if(next_pc[1:0]!=0)illegal=1;
  if((load || store) && ((f3[1:0]==1 && address[0]) || (f3[1:0]==2 && address[1:0]!=0)))illegal=1;
 end
endmodule
