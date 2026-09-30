// Instruction-level LC-3 datapath. Interrupt delivery and privilege stack
// switching belong to a surrounding system; RTI checks the current PSR mode.
module lc3_core #(
    parameter RESET_PC  = 16'h3000,
    parameter RESET_PSR = 16'h8002
) (
    input clk,
    rst,
    run,
    halt_request,
    output reg [15:0] memory_address,
    output reg [15:0] memory_data,
    output reg memory_write,
    input [15:0] memory_q,
    output reg [15:0] pc,
    instruction,
    psr,
    output [15:0] r0,
    r1,
    r2,
    r3,
    r6,
    r7,
    output reg [3:0] state,
    output reg [7:0] retired,
    output reg halted,
    fault
);
  localparam FETCH=0,EXEC=1,LOAD=2,STORE=3,INDIRECT=4,VECTOR=5,RTI_PC=6,RTI_PSR=7;
  reg [15:0] address, store_data;
  reg  [ 2:0] load_dest;
  wire [ 3:0] op = instruction[15:12];
  wire [15:0] offset9 = {{7{instruction[8]}}, instruction[8:0]};
  wire [15:0] offset6 = {{10{instruction[5]}}, instruction[5:0]};
  wire [15:0] offset11 = {{5{instruction[10]}}, instruction[10:0]};
  wire [15:0] imm5 = {{11{instruction[4]}}, instruction[4:0]};
  wire [15:0] pc_next = pc + 16'd1;
  wire [15:0] a, b;
  reg register_write, cc_write;
  reg  [ 2:0] dest;
  reg  [15:0] register_data;
  wire [ 2:0] read_x = (state == RTI_PC || state == RTI_PSR) ? 3'd6 : instruction[8:6];
  wire [ 2:0] read_y = (op == 3 || op == 7 || op == 11) ? instruction[11:9] : instruction[2:0];
  lc3_registers registers (
      clk,
      rst,
      register_write,
      dest,
      read_x,
      read_y,
      register_data,
      a,
      b,
      r0,
      r1,
      r2,
      r3,
      r6,
      r7
  );
  always @* begin
    memory_address = pc;
    memory_data = store_data;
    memory_write = 0;
    register_write = 0;
    cc_write = 0;
    dest = instruction[11:9];
    register_data = 0;
    case (state)
      LOAD: begin
        memory_address = address;
        dest = load_dest;
        register_data = memory_q;
        register_write = 1;
        cc_write = 1;
      end
      STORE: begin
        memory_address = address;
        memory_write   = 1;
      end
      INDIRECT, VECTOR: memory_address = address;
      RTI_PC: memory_address = r6;
      RTI_PSR: begin
        memory_address = r6 + 16'd1;
        dest = 6;
        register_data = r6 + 16'd2;
        register_write = 1;
      end
      EXEC:
      case (op)
        1: begin
          register_write = 1;
          cc_write = 1;
          register_data = a + (instruction[5] ? imm5 : b);
        end
        5: begin
          register_write = 1;
          cc_write = 1;
          register_data = a & (instruction[5] ? imm5 : b);
        end
        9: begin
          register_write = 1;
          cc_write = 1;
          register_data = ~a;
        end
        14: begin
          register_write = 1;
          cc_write = 1;
          register_data = pc_next + offset9;
        end
        4, 15: begin
          register_write = 1;
          dest = 7;
          register_data = pc_next;
        end
      endcase
    endcase
    if (rst || !run || halted || fault) begin
      register_write = 0;
      cc_write = 0;
      memory_write = 0;
    end
  end
  always @(posedge clk or posedge rst) begin
    if (rst) begin
      pc <= RESET_PC;
      psr <= RESET_PSR;
      instruction <= 0;
      state <= FETCH;
      retired <= 0;
      halted <= 0;
      fault <= 0;
      address <= 0;
      store_data <= 0;
      load_dest <= 0;
    end else if (halt_request) halted <= 1;
    else if (run && !halted && !fault) begin
      if (cc_write) psr[2:0] <= register_data == 0 ? 3'b010 : (register_data[15] ? 3'b100 : 3'b001);
      case (state)
        FETCH: begin
          instruction <= memory_q;
          state <= EXEC;
        end
        EXEC: begin
          pc <= pc_next;
          state <= FETCH;
          retired <= retired + 1'b1;
          load_dest <= instruction[11:9];
          case (op)
            0:  if (|(instruction[11:9] & psr[2:0])) pc <= pc_next + offset9;
            1, 5, 9, 14: begin
            end
            2: begin
              address <= pc_next + offset9;
              state   <= LOAD;
            end
            3: begin
              address <= pc_next + offset9;
              store_data <= b;
              state <= STORE;
            end
            4:  pc <= instruction[11] ? pc_next + offset11 : a;
            6: begin
              address <= a + offset6;
              state   <= LOAD;
            end
            7: begin
              address <= a + offset6;
              store_data <= b;
              state <= STORE;
            end
            8:  if (psr[15]) fault <= 1;
 else state <= RTI_PC;
            10, 11: begin
              address <= pc_next + offset9;
              store_data <= b;
              state <= INDIRECT;
            end
            12: pc <= a;
            13: fault <= 1;
            15: begin
              address <= {8'b0, instruction[7:0]};
              state   <= VECTOR;
            end
          endcase
        end
        LOAD, STORE: state <= FETCH;
        INDIRECT: begin
          address <= memory_q;
          state   <= op == 10 ? LOAD : STORE;
        end
        VECTOR: begin
          pc <= memory_q;
          state <= FETCH;
        end
        RTI_PC: begin
          pc <= memory_q;
          state <= RTI_PSR;
        end
        RTI_PSR: begin
          psr   <= memory_q;
          state <= FETCH;
        end
        default: fault <= 1;
      endcase
    end
  end
endmodule
