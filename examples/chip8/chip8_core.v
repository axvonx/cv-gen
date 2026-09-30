// Original CHIP-8 hardware interpreter. Shifts use VY; FX55/65 advance I.
module chip8_core (
    input clk,
    rst,
    run,
    timer_tick,
    input [15:0] keys,
    input [7:0] random_byte,
    output [11:0] memory_address,
    output [7:0] memory_data,
    output memory_write,
    input [7:0] memory_q,
    output [10:0] pixel_address,
    output pixel_write,
    pixel_data,
    input pixel_q,
    output reg [11:0] pc,
    index_reg,
    output reg [15:0] instruction,
    output [7:0] v0,
    vf,
    output reg [7:0] delay_timer,
    sound_timer,
    output reg [4:0] state,
    output reg [7:0] retired,
    output reg fault
);
  localparam FETCH_HI=0,FETCH_LO=1,EXEC=2,STORE=3,LOAD=4,BCD=5,
  ROW_READ=6,PIX_READ=7,PIX_WRITE=8,CLEAR=9,WAIT_KEY=10;
  reg [4:0] sp;
  reg [3:0] cursor, row;
  reg [2:0] column;
  reg [7:0] sprite, draw_x, draw_y, bcd_value;
  reg old_pixel, collision;
  reg [3:0] key_number;
  reg key_found;
  integer k;
  always @* begin
    key_found  = 0;
    key_number = 0;
    for (k = 15; k >= 0; k = k - 1)
    if (keys[k]) begin
      key_found  = 1;
      key_number = k;
    end
  end
  wire [3:0] x = instruction[11:8], y = instruction[7:4];
  wire [7:0] a, b, alu_value;
  wire alu_flag, alu_flag_write, alu_valid;
  wire register_write, flag_write, flag_value;
  wire [3:0] dest, read_x;
  wire [7:0] register_data;
  chip8_alu alu (
      instruction[3:0],
      a,
      b,
      alu_value,
      alu_flag,
      alu_flag_write,
      alu_valid
  );
  chip8_registers registers (
      clk,
      rst,
      register_write,
      flag_write,
      dest,
      read_x,
      y,
      register_data,
      flag_value,
      a,
      b,
      v0,
      vf
  );
  wire stack_push = run && !fault && state == EXEC && instruction[15:12] == 2 && sp < 16;
  wire [3:0] stack_address = stack_push ? sp[3:0] : (sp[3:0] - 4'd1);
  wire [11:0] return_address;
  chip8_stack stack (
      clk,
      rst,
      stack_push,
      stack_address,
      pc + 12'd2,
      return_address
  );
  wire last_pixel = column == 7 && row == instruction[3:0] - 1;
  wire hit = old_pixel && sprite[7-column];
  wire [5:0] pixel_x = draw_x[5:0] + {3'b0, column};
  wire [4:0] pixel_y = draw_y[4:0] + {1'b0, row};
  chip8_control control (
      state,
      pc,
      index_reg,
      instruction,
      cursor,
      row,
      column,
      a,
      b,
      bcd_value,
      draw_x,
      draw_y,
      sprite,
      old_pixel,
      collision,
      clear_cursor,
      key_found,
      key_number,
      delay_timer,
      random_byte,
      memory_q,
      alu_value,
      alu_valid,
      alu_flag_write,
      alu_flag,
      run,
      fault,
      rst,
      memory_address,
      memory_data,
      memory_write,
      pixel_address,
      pixel_write,
      pixel_data,
      register_write,
      flag_write,
      flag_value,
      dest,
      read_x,
      register_data
  );
  reg [10:0] clear_cursor;
  always @(posedge clk or posedge rst) begin
    if (rst) begin
      pc <= 12'h200;
      index_reg <= 0;
      instruction <= 0;
      state <= FETCH_HI;
      retired <= 0;
      fault <= 0;
      sp <= 0;
      cursor <= 0;
      row <= 0;
      column <= 0;
      sprite <= 0;
      draw_x <= 0;
      draw_y <= 0;
      old_pixel <= 0;
      collision <= 0;
      bcd_value <= 0;
      clear_cursor <= 0;
      delay_timer <= 0;
      sound_timer <= 0;
    end else begin
      if (timer_tick) begin
        if (delay_timer != 0) delay_timer <= delay_timer - 1'b1;
        if (sound_timer != 0) sound_timer <= sound_timer - 1'b1;
      end
      if (run && !fault)
        case (state)
          FETCH_HI: begin
            instruction[15:8] <= memory_q;
            state <= FETCH_LO;
          end
          FETCH_LO: begin
            instruction[7:0] <= memory_q;
            state <= EXEC;
          end
          EXEC: begin
            pc <= pc + 12'd2;
            state <= FETCH_HI;
            retired <= retired + 1'b1;
            case (instruction[15:12])
              0:
              if (instruction == 16'h00e0) begin
                state <= CLEAR;
                clear_cursor <= 0;
              end else if (instruction == 16'h00ee) begin
                if (sp == 0) fault <= 1;
                else begin
                  pc <= return_address;
                  sp <= sp - 1'b1;
                end
              end else fault <= 1;  // 0NNN needs a COSMAC host, outside this hardware interpreter
              1:  pc <= instruction[11:0];
              2:
              if (sp == 16) fault <= 1;
              else begin
                pc <= instruction[11:0];
                sp <= sp + 1'b1;
              end
              3:  if (a == instruction[7:0]) pc <= pc + 12'd4;
              4:  if (a != instruction[7:0]) pc <= pc + 12'd4;
              5:  if (instruction[3:0] != 0) fault <= 1;
 else if (a == b) pc <= pc + 12'd4;
              6, 7: begin
              end
              8:  if (!alu_valid) fault <= 1;
              9:  if (instruction[3:0] != 0) fault <= 1;
 else if (a != b) pc <= pc + 12'd4;
              10: index_reg <= instruction[11:0];
              11: pc <= instruction[11:0] + {4'b0, v0};
              12: begin
              end
              13: begin
                if (instruction[3:0] != 0) begin
                  state <= ROW_READ;
                  draw_x <= a;
                  draw_y <= b;
                  row <= 0;
                  column <= 0;
                  collision <= 0;
                end else fault <= 1;  // DXY0 is a Super-CHIP extension
              end
              14:
              if (instruction[7:0] == 8'h9e) begin
                if (a < 16 && keys[a[3:0]]) pc <= pc + 12'd4;
              end else if (instruction[7:0] == 8'ha1) begin
                if (a >= 16 || !keys[a[3:0]]) pc <= pc + 12'd4;
              end else fault <= 1;
              15:
              case (instruction[7:0])
                7: begin
                end
                10: state <= WAIT_KEY;
                21: delay_timer <= a;
                24: sound_timer <= a;
                30: index_reg <= index_reg + {4'b0, a};
                41: index_reg <= {8'b0, a[3:0]} * 12'd5;
                51: begin
                  bcd_value <= a;
                  cursor <= 0;
                  state <= BCD;
                end
                85: begin
                  cursor <= 0;
                  state  <= STORE;
                end
                101: begin
                  cursor <= 0;
                  state  <= LOAD;
                end
                default: fault <= 1;
              endcase
            endcase
          end
          STORE, LOAD:
          if (cursor == x) begin
            index_reg <= index_reg + {8'b0, x} + 12'd1;
            state <= FETCH_HI;
          end else cursor <= cursor + 1'b1;
          BCD:
          if (cursor == 2) state <= FETCH_HI;
          else cursor <= cursor + 1'b1;
          ROW_READ: begin
            sprite <= memory_q;
            column <= 0;
            state  <= PIX_READ;
          end
          PIX_READ: begin
            old_pixel <= pixel_q;
            state <= PIX_WRITE;
          end
          PIX_WRITE: begin
            collision <= collision | hit;
            if (column == 7) begin
              if (last_pixel) state <= FETCH_HI;
              else begin
                row   <= row + 1'b1;
                state <= ROW_READ;
              end
            end else begin
              column <= column + 1'b1;
              state  <= PIX_READ;
            end
          end
          CLEAR:
          if (clear_cursor == 2047) state <= FETCH_HI;
          else clear_cursor <= clear_cursor + 1'b1;
          WAIT_KEY: if (key_found) state <= FETCH_HI;
          default: fault <= 1;
        endcase
    end
  end
endmodule
