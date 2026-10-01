// DOOM machine bus: 16 MiB RAM with a null guard, word-only MMIO at 0x10000000,
// the frame handshake, an 8-entry key FIFO, 64-bit counters and fault causes.
// The memory map is examples/doom/runtime/machine.h. No signal is wider than 32
// bits, CircuitVerse's limit, so 64-bit counters are kept as two halves.
module rv32_doom_bus(input clk,rst,run,load_enable,inspect,
 input [23:0] load_address,peek_address,input [31:0] load_data,
 input [1:0] state,access_kind,input [31:0] pc,address,data,access_address,
 input write,input [2:0] size,input [15:0] retired,input cpu_active,core_fault,
 input frame_ack,key_push,input [8:0] key_data,
 output [31:0] memory_q,peek_word,output bus_fault,
 output reg done,frame_pending,output reg [31:0] exit_code,frame_info,
 output [2:0] fault_cause,output console_write,output [7:0] console_data,
 output key_full,output reg [31:0] cycle_lo,cycle_hi,output [31:0] instret_lo,instret_hi);
 localparam FETCH=0,EXECUTE=1,MEMORY=2;
 wire [31:0] ram_q;
 wire in_ram=access_address<32'h1000000 && access_address>=32'h1000;
 wire in_mmio=access_address[31:8]==24'h100000 && access_address[7:0]<8'h28;
 wire mmio_ok=in_mmio && size==2 && access_address[7:0]!=8'h14;
 wire fetch_fault=pc>=32'h1000000 || pc[1:0]!=0;
 wire data_fault=access_kind!=0 && !in_ram && !mmio_ok;
 assign bus_fault=state==FETCH ? fetch_fault : state==EXECUTE && data_fault;
 wire misaligned=(size[1:0]==1 && access_address[0]) || (size[1:0]==2 && access_address[1:0]!=0);
 rv32_doom_memory memory(clk,rst,run,load_enable,inspect,load_address,peek_address,load_data,
                         address,data,size,write,ram_q);
 assign peek_word=ram_q;
 // Stores reach MMIO in the MEMORY state, once the bus has accepted the access.
 wire mmio_write=write && address[31:8]==24'h100000;
 wire [7:0] offset=address[7:0];
 assign console_write=mmio_write && offset==8'h00;
 assign console_data=data[7:0];
 // Key FIFO: the host pushes {pressed,key}; the CPU peeks at 0x0c and pops at 0x10.
 reg [8:0] keys[0:7];
 reg [2:0] key_head,key_tail;
 reg [3:0] key_count;
 assign key_full=key_count==8;
 wire key_pop=mmio_write && offset==8'h10 && key_count!=0;
 wire [8:0] key_front=keys[key_head];
 wire [31:0] key_word=key_count==0 ? 32'b0 : {22'b0,key_front[8],1'b1,key_front[7:0]};
 // retired is the core's 16-bit counter; count its wraps for a 64-bit instret,
 // correcting combinationally in the cycle right after a wrap.
 reg [15:0] wraps_lo;
 reg [31:0] wraps_hi;
 reg previous_top;
 wire wrapped=previous_top && !retired[15];
 wire [16:0] lo_now={1'b0,wraps_lo}+{16'b0,wrapped};
 assign instret_lo={lo_now[15:0],retired};
 assign instret_hi=wraps_hi+{31'b0,lo_now[16]};
 always @(posedge clk or posedge rst)
  if(rst)begin
   done<=0;frame_pending<=0;exit_code<=0;frame_info<=0;cycle_lo<=0;cycle_hi<=0;
   key_head<=0;key_tail<=0;key_count<=0;wraps_lo<=0;wraps_hi<=0;previous_top<=0;
  end else begin
   previous_top<=retired[15];
   if(wrapped)begin wraps_lo<=lo_now[15:0];wraps_hi<=instret_hi;end
   if(cpu_active)begin
    cycle_lo<=cycle_lo+1;
    if(cycle_lo==32'hffffffff)cycle_hi<=cycle_hi+1;
   end
   if(mmio_write && offset==8'h04)begin done<=1;exit_code<=data;end
   if(mmio_write && offset==8'h08)begin frame_pending<=1;frame_info<=data;end
   if(frame_ack)frame_pending<=0;
   if(key_push && !key_full)begin keys[key_tail]<=key_data;key_tail<=key_tail+1;end
   key_count<=key_count+{3'b0,key_push && !key_full}-{3'b0,key_pop};
   if(key_pop)key_head<=key_head+1;
  end
 // A faulted core holds state, pc and the decoded access, so the cause is derived
 // from them: fetch, then bus (access/MMIO), then misalignment, else illegal.
 assign fault_cause=!core_fault ? 3'd0 : state==FETCH ? 3'd2 :
                    state==EXECUTE && data_fault ? (in_mmio ? 3'd5 : 3'd4) :
                    access_kind!=0 && misaligned ? 3'd3 : 3'd1;
 reg [31:0] mmio_q;
 always @* case(access_address[7:0])
  8'h0c:mmio_q=key_word;
  8'h18:mmio_q=cycle_lo;
  8'h1c:mmio_q=cycle_hi;
  8'h20:mmio_q=instret_lo;
  8'h24:mmio_q=instret_hi;
  default:mmio_q=0;
 endcase
 assign memory_q=address[31:8]==24'h100000 ? mmio_q : ram_q;
endmodule
