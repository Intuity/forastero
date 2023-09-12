# Forastero

Forastero is a library for writing better testbenches with [cocotb](http://cocotb.org),
taking some inspiration from the
[Unified Verification Methodology (UVM)](https://en.wikipedia.org/wiki/Universal_Verification_Methodology)
but distilling it to just the most useful parts.

For those unfamiliar, [cocotb](http://cocotb.org) is a Python framework for
writing testbenches for hardware designs written in a HDL such as SystemVerilog.
It is agnostic to the simulator being used, working equally well with opensource
and commercial solutions, which is rather unique for the EDA industry.

In some ways Forastero is a spiritual successor to
[cocotb-bus](https://github.com/cocotb/cocotb-bus), which has now fallen out of
active support. Forastero takes much of its inspiration from cocotb-bus, but
takes a different view to how the testbench and its various components interact.

## What makes Forastero different?

### Testbench Class

Forastero provides a way to write testbenches where common drivers and monitors
are defined and attached to the design in a class, rather than as part of each
test sequence. This is subtly different to the recommendations laid out in
[cocotb's documentation](https://docs.cocotb.org/en/stable/quickstart.html), but
leads to less code duplcation and makes it faster to add new tests.

For example, the following code defines a testbench with a driver attached to a
stream input port of the design:

```python
from forastero import BaseBench, IORole

from .stream import StreamInitiator, StreamIO

class Testbench(BaseBench):
    def __init__(self, dut):
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.RESPONDER)
        self.register("stream_init", StreamInitiator(self,
                                                     stream_io,
                                                     self.clk,
                                                     self.rst))
```

Highlighting a few interesting snippets:

 * `Testbench` inherits from `forastero.BaseBench` that provides a baseline
   setup for a testbench;
 * `super().__init__(...)` is called with a handle to the DUT as well as the
   primary clock and reset signals of the design, these are used in standard
   sequences (such as waiting for a test to end) to observe time passing;
 * `StreamIO(...)` wraps multiple signals on the boundary of the design up in
   a single object that can be referenced by drivers and monitors;
 * `self.register("stream_init", StreamInitiator(...))` creates an instance of
   a driver and registers it with the testbench using the name 'stream_init',
   the `StreamIO` object, clock, and reset are passed into the driver.

Forastero has some assumptions of how your design looks, specifically around
how signals are named. It assumes the following naming convention:

 * Ports are prefixed according to their direction with inputs prefixed by `i_`
   and outputs by `o_`;
 * Port names then have a common section depending on their purpose, for example
   all signal relating to the `stream` interface start with either `i_stream_`
   or `o_stream_`;
 * Finally the port name ends with its purpose, for example `i_stream_data`.

Such a design would look like:

```verilog
module arbiter (
      input  logic        i_clk
    , input  logic        i_rst
    , input  logic [31:0] i_stream_data
    , input  logic        i_stream_valid
    , output logic        o_stream_ready
    // ...other signals...
);

// ...implementation...

endmodule : arbiter
```

This style is evidently opinionated, but not without reason as it makes it clear
the exact purpose and direction of any signal within a line without having to
cross-reference the port declaration. If it is not to your taste, the code for
the `BaseIO` object is easily extensible.

### Writing Testcases

cocotb provides the `@cocotb.test()` decorator to distinguish a Python function
as a test, Forastero replaces this with a decorator defined by the testbench
class. For example:

```python
from ..testbench import Testbench

@Testbench.testcase()
async def smoke(tb : Testbench):
    ...
```

As shown above, `@cocotb.test()` is replaced by `@Testbench.testcase()` - this
performs all the same functions but replaces the `dut` argument that cocotb
normally provides with a pointer to an instance of `Testbench` instead. This
decorator does provide some new arguments:

 * `reset` - defaults to `True`, but if set to `False` it will skip the standard
   reset and initialisation preamble of the testbench and immediately start the
   test;
 * `timeout` - sets the maximum number of clock ticks that the testcase can run
   for before the testbench assumes it is a failure and stops it, this defaults
   to `10000`.
 * `shutdown_loops` - overrides the number of loops performed at the end of
   simulation to determine if all monitors, drivers, and scoreboards have
   drained, this defaults to `2`;
 * `shutdown_delay` - overrides the delay between loops of the shutdown sequence,
   this defaults to `100` clock ticks.

## Why the name Forastero?

Forastero is the most commonly grown variety of cacao tree, providing a large
part of the world's supply of cocoa beans. The name was chosen as a bit of a
word play with the 'coco' part of 'cocotb'.
