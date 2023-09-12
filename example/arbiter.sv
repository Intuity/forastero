module arbiter (
      input  logic        i_clk
    , input  logic        i_rst
    // A
    , input  logic [31:0] i_a_data
    , input  logic        i_a_valid
    , output logic        o_a_ready
    // B
    , input  logic [31:0] i_b_data
    , input  logic        i_b_valid
    , output logic        o_b_ready
    // Arbitrated
    , output logic [31:0] o_x_data
    , output logic        o_x_valid
    , input  logic        i_x_ready
);

logic [31:0] arb_data_d, arb_data_q;
logic        arb_valid_d, arb_valid_q;
logic        arb_choice_d, arb_choice_q;

assign arb_choice_d = (arb_choice_q ^ i_a_valid) ? 1'b0 : 1'b1;

assign arb_valid_d = (arb_valid_q && !i_x_ready) ||
                     (i_a_valid || i_b_valid);

assign arb_data_d  = (!arb_valid_q || i_x_ready)
                        ? ((arb_choice_d == 'd0) ? i_a_data : i_b_data)
                        : arb_data_q;

assign o_a_ready = (!arb_valid_q || i_x_ready) && (arb_choice_d == 'd0);
assign o_b_ready = (!arb_valid_q || i_x_ready) && (arb_choice_d == 'd1);

assign o_x_data  = arb_data_q;
assign o_x_valid = arb_valid_q;

always_ff @(posedge i_clk, posedge i_rst) begin : ff_arb_choice
    if (i_rst) begin
        arb_choice_q <= 'd0;
    end else if (arb_valid_d) begin
        arb_choice_q <= arb_choice_d;
    end
end

always_ff @(posedge i_clk, posedge i_rst) begin : ff_arb_data
    if (i_rst) begin
        { arb_data_q, arb_valid_q } <= 'd0;
    end else begin
        { arb_data_q, arb_valid_q } <= { arb_data_d, arb_valid_d };
    end
end

endmodule : arbiter
