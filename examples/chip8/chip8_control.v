module chip8_control (
    input [4:0] state,
    input [11:0] pc,
    index_reg,
    input [15:0] instruction,
    input [3:0] cursor,
    row,
    input [2:0] column,
    input [7:0] a,
    b,
    bcd_value,
    draw_x,
    draw_y,
    sprite,
    input old_pixel,
    collision,
    input [10:0] clear_cursor,
    input key_found,
    input [3:0] key_number,
    input [7:0] delay_timer,
    random_byte,
    memory_q,
    alu_value,
    input alu_valid,
    alu_flag_write,
    alu_flag,
    input run,
    fault,
    rst,
    output reg [11:0] memory_address,
    output reg [7:0] memory_data,
    output reg memory_write,
    output reg [10:0] pixel_address,
    output reg pixel_write,
    pixel_data,
    output reg register_write,
    flag_write,
    flag_value,
    output reg [3:0] dest,
    read_x,
    output reg [7:0] register_data
);
  localparam FETCH_HI=0,FETCH_LO=1,EXEC=2,STORE=3,LOAD=4,BCD=5,
  ROW_READ=6,PIX_READ=7,PIX_WRITE=8,CLEAR=9,WAIT_KEY=10;
  wire [3:0] x = instruction[11:8];
  wire [7:0] hundreds, tens, ones;
  chip8_bcd bcd (
      bcd_value,
      hundreds,
      tens,
      ones
  );
  wire last_pixel = column == 7 && row == instruction[3:0] - 1;
  wire hit = old_pixel && sprite[7-column];
  wire [5:0] pixel_x = draw_x[5:0] + {3'b0, column};
  wire [4:0] pixel_y = draw_y[4:0] + {1'b0, row};
  always @* begin
    memory_address = pc;
    memory_data = 0;
    memory_write = 0;
    pixel_address = {pixel_y, pixel_x};
    pixel_write = 0;
    pixel_data = 0;
    register_write = 0;
    flag_write = 0;
    flag_value = 0;
    register_data = 0;
    dest = x;
    read_x = x;
    case (state)
      FETCH_LO: memory_address = pc + 12'd1;
      STORE: begin
        memory_address = index_reg + {8'b0, cursor};
        memory_data = a;
        memory_write = 1;
        read_x = cursor;
      end
      LOAD: begin
        memory_address = index_reg + {8'b0, cursor};
        dest = cursor;
        register_data = memory_q;
        register_write = 1;
      end
      BCD: begin
        memory_address = index_reg + {8'b0, cursor};
        memory_write   = 1;
        case (cursor)
          0: memory_data = hundreds;
          1: memory_data = tens;
          default: memory_data = ones;
        endcase
      end
      ROW_READ: memory_address = index_reg + {8'b0, row};
      PIX_WRITE: begin
        pixel_write = 1;
        pixel_data  = old_pixel ^ sprite[7-column];
        if (last_pixel) begin
          flag_write = 1;
          flag_value = collision | hit;
        end
      end
      CLEAR: begin
      end
      WAIT_KEY:
      if (key_found) begin
        register_write = 1;
        register_data  = {4'b0, key_number};
      end
      EXEC:
      case (instruction[15:12])
        6: begin
          register_write = 1;
          register_data  = instruction[7:0];
        end
        7: begin
          register_write = 1;
          register_data  = a + instruction[7:0];
        end
        8: begin
          register_write = alu_valid;
          register_data = alu_value;
          flag_write = alu_flag_write;
          flag_value = alu_flag;
        end
        12: begin
          register_write = 1;
          register_data  = random_byte & instruction[7:0];
        end
        15:
        if (instruction[7:0] == 7) begin
          register_write = 1;
          register_data  = delay_timer;
        end
      endcase
    endcase
    if (state == CLEAR) begin
      pixel_address = clear_cursor;
      pixel_write = 1;
      pixel_data = 0;
    end
    if (!run || fault || rst) begin
      memory_write = 0;
      pixel_write = 0;
      register_write = 0;
      flag_write = 0;
    end
  end
endmodule
