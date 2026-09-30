module lc3_demo (
    input clk,
    rst,
    run,
    input load_enable,
    input [15:0] load_address,
    load_data,
    input demo_enable,
    output [15:0] pc,
    instruction,
    psr,
    r0,
    r1,
    r2,
    r3,
    r6,
    r7,
    output [3:0] state,
    output [7:0] retired,
    output halted,
    fault,
    done
);
  wire [15:0] memory_address, memory_data, memory_q, ram_q, rom_q;
  wire memory_write, rom_valid;
  wire halt_request = memory_write && memory_address == 16'hfffe && !memory_data[15];
  lc3_core cpu (
      clk,
      rst,
      run && !load_enable,
      halt_request,
      memory_address,
      memory_data,
      memory_write,
      memory_q,
      pc,
      instruction,
      psr,
      r0,
      r1,
      r2,
      r3,
      r6,
      r7,
      state,
      retired,
      halted,
      fault
  );
  wire [15:0] ram_address = load_enable ? load_address : memory_address;
  wire [15:0] ram_data = load_enable ? load_data : memory_data;
  async_ram #(
      .DATA(16),
      .ADDR(16)
  ) memory (
      ram_address,
      ram_data,
      !clk && !rst && (load_enable || memory_write),
      ram_q
  );
  lc3_rom rom (
      memory_address,
      rom_q,
      rom_valid
  );
  assign memory_q = demo_enable && rom_valid ? rom_q : ram_q;
  assign done = halted && !fault;
endmodule
