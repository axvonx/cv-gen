// M=1 adds the RV32M extension (rv32_muldiv.v); M=0 is the RV32I core.
module rv32_core #(parameter M=0) (input clk,rst,run,input bus_fault,
 input [31:0] memory_q,output [31:0] memory_address,memory_data,
 output memory_write,output [2:0] memory_size,
 output reg [31:0] pc,instruction,output [31:0] a0,sp,
 output reg [1:0] state,output reg [15:0] retired,output reg fault,output [31:0] access_address,output [1:0] access_kind);
 localparam FETCH=0,EXECUTE=1,MEMORY=2;
 wire [31:0] a,b,value,base_value,next_pc,address,loaded,unused_shift;
 wire wr,ld,st,illegal,base_illegal;
 wire [2:0] size;
 wire [3:0] unused_mask;
 assign access_address=address;assign access_kind={st,ld};
 wire active=run && !fault;
 rv32_decode decoder(instruction,a,b,pc,base_value,next_pc,address,wr,ld,st,base_illegal,size);
 generate if(M)begin:m_extension
  // OP with funct7=1: the decoder already writes rd and advances pc by 4.
  wire multiply_divide=instruction[6:0]==7'h33 && instruction[31:25]==7'h01;
  wire [31:0] result;
  rv32_muldiv muldiv(a,b,instruction[14:12],result);
  assign value=multiply_divide ? result : base_value;
  assign illegal=base_illegal && !multiply_divide;
 end else begin:base
  assign value=base_value;
  assign illegal=base_illegal;
 end endgenerate
 rv32_lanes loads(address[1:0],size,memory_q,32'b0,loaded,unused_shift,unused_mask);
 wire register_enable=active && !bus_fault && ((state==EXECUTE && !illegal && wr) || (state==MEMORY && !st));
 rv32_registers registers(clk,rst,register_enable,instruction[11:7],instruction[19:15],instruction[24:20],state==MEMORY ? loaded : value,a,b,a0,sp);
 assign memory_address=state==MEMORY ? address : pc;
 assign memory_data=b;
 assign memory_size=size;
 assign memory_write=active && state==MEMORY && st;
 always @(posedge clk or posedge rst) begin
  if(rst)begin pc<=0;instruction<=0;state<=FETCH;retired<=0;fault<=0;end
  else if(active)begin
   if(bus_fault)fault<=1;
   else case(state)
    FETCH:begin instruction<=memory_q;state<=EXECUTE;end
    EXECUTE:begin
     if(illegal)fault<=1;
     else if(ld || st)begin state<=MEMORY;end
     else begin pc<=next_pc;retired<=retired+1;state<=FETCH;end
    end
    MEMORY:begin pc<=pc+4;retired<=retired+1;state<=FETCH;end
    default:fault<=1;
   endcase
  end
 end
endmodule
