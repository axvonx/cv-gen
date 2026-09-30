// Small accumulator CPU for exploring the cv-gen pipeline.
// Instruction fields are separate ports to keep the CircuitVerse block view clear.
module teaching_cpu (
    input clk,
    input rst,
    input [2:0] opcode,
    input [7:0] immediate,
    output reg [3:0] pc,
    output reg [7:0] accumulator,
    output reg [7:0] out_value,
    output reg halted
);
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            pc <= 4'd0;
            accumulator <= 8'd0;
            out_value <= 8'd0;
            halted <= 1'b0;
        end else if (!halted) begin
            pc <= pc + 4'd1;
            case (opcode)
                3'd1: accumulator <= immediate;                 // LDI n
                3'd2: accumulator <= accumulator + immediate;   // ADD n
                3'd3: out_value <= accumulator;                 // OUT
                3'd4: begin halted <= 1'b1; pc <= pc; end       // HALT
                default: begin end                              // NOP
            endcase
        end
    end
endmodule
