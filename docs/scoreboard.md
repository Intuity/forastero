## Simple Channels

When `self.register(...)` is called it will register the monitor against the
scoreboard and queue captured transactions into a dedicated channel (unless
`scoreboard=False` is set). If no other parameters are provided then the
scoreboard will create a simple channel.

A simple channel will expect all transactions submitted to the reference queue
to appear in the same order in the monitor's queue, and whenever a mismatch is
detected it will flag an error.

```python title="tb/testbench.py"
from forastero import BaseBench, IORole
from .stream import StreamIO, StreamMonitor

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.INITIATOR)
        self.register("stream_mon",
                      StreamMonitor(self, stream_io, self.clk, self.rst))

    def model_stream(self):
        self.scoreboard.channels["stream_mon"].push_reference(StreamTransaction(...))
```

## Match Window Channels

Sometimes it is necessary to relax the precise ordering matches between captured
and reference transactions - for example if a black-box component is performing
an arbitration between different upstream initiators onto a single downstream
port then the testbench may want to just check for transaction consistency
without modelling the exact ordering function implemented by the hardware.

To support this, the scoreboard offers matching windows - allowing a captured
transaction to match against any of the first `N` entries of the reference queue.
This can be configured using the `sb_match_window` argument when registering a
monitor.

In the example shown below the matching window is set to a value of 4, this
means that each captured transaction can be matched against entries `0`, `1`,
`2`, or `3` of the reference queue.

```python title="tb/testbench.py"
from forastero import BaseBench, IORole
from .stream import StreamIO, StreamMonitor

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        ds_io = dsIO(dut, "ds", IORole.INITIATOR)
        self.register("ds_mon",
                      StreamMonitor(self, ds_io, self.clk, self.rst),
                      sb_match_window=4)

    def model_stream(self):
        self.scoreboard.channels["ds_mon"].push_reference(StreamTransaction(...))
```

## Funnel Channels

Another option is to register the monitor with multiple named scoreboard queues,
thus creating a "funnel" channel. In this case each named queue of the channel
must maintain order, but the scoreboard can pop entries from different queus in
any order - this is great for blackbox verification of components like arbiters
where the decision on which transaction is going to be taken may be influenced
by many factors internal to the device.

```python title="tb/testbench.py"
from forastero import BaseBench, IORole
from .stream import StreamIO, StreamMonitor

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.INITIATOR)
        self.register("arb_output_mon",
                      StreamMonitor(self, stream_io, self.clk, self.rst),
                      sb_queues=("a", "b", "c"))

    def model_arbiter_src_b(self):
        self.scoreboard.channels["arb_output_mon"].push_reference(
            "b", StreamTransaction(...)
        )
```

## Scoreboard Channel Timeouts

While each registered testcase can provide a timeout, this in many cases may be
set at a very high time to cope with complex, long running testcases. To provide
a finer granularity of timeout control, timeouts may be configured specifically
to scoreboard channels that specify how long it is acceptable for a transaction
to sit at the front of the monitor's queue before the scoreboard matches it to
a reference transaction. There are two key parameters to `self.register(...)`:

 * `sb_timeout_ns` - the maximum acceptable age a transaction may be at the front
   of the monitor's channel. The age is determined by substracting the transaction's
   `timestamp` field (a default property of `BaseTransaction`) from the current
   simulation time.

 * `sb_polling_ns` - the frequency with which to check the front of the scoreboard's
   monitor queue, this defaults to `100 ns`.

Due to the interaction of the polling timeout and polling period, transactions
may live longer than the timeout in certain cases but this is bounded by a
maximum delay of one polling interval.

```python title="tb/testbench.py"
from forastero import BaseBench, IORole
from .stream import StreamIO, StreamMonitor

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.INITIATOR)
        self.register("stream_mon",
                      StreamMonitor(self, stream_io, self.clk, self.rst),
                      sb_timeout_ns=10)
```

## Draining Policy

The default behaviour of scoreboard channels is to block testcase completion
until both the monitor and reference queues have fully emptied, however this can
be customised by overriding the draining policy.

There are 4 supported draining policies:

 * [MON_AND_REF](#forastero.scoreboard.DrainPolicy.MON_AND_REF) - this is the default
   behaviour and will block completion until both the monitor and reference queues
   have fully emptied;
 * [MON_ONLY](#forastero.scoreboard.DrainPolicy.MON_AND_REF) - only block until the
   monitor queue has drained, ignoring the reference queue;
 * [REF_ONLY](#forastero.scoreboard.DrainPolicy.MON_AND_REF) - only block until the
   reference queue has drained, ignoring the monitor queue;
 * [NON_BLOCKING](#forastero.scoreboard.DrainPolicy.MON_AND_REF) - neither the
   monitor or reference queues need to drain for the scoreboard to shut down.

The policy can be selected when registering the scoreboard channel:

```python title="tb/testbench.py"
from forastero import BaseBench, DrainPolicy, IORole
from .stream import StreamIO, StreamMonitor

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.INITIATOR)
        self.register("stream_mon",
                      StreamMonitor(self, stream_io, self.clk, self.rst),
                      sb_drain_policy=DrainPolicy.REF_ONLY)
```

!!! note

    If a scoreboard channel still contains entries in either the monitor or
    reference queues, but these are ignored due to the draining policy, a warning
    message will be raised from the scoreboard channel during shutdown.

---

::: forastero.scoreboard.Scoreboard
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.scoreboard.DrainPolicy
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
