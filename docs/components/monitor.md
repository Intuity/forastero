Monitors inherit from [BaseMonitor](#forastero.monitor.BaseMonitor) and must
implement the `monitor` method, that observe signals on or within the DUT and
generate transactions for other parts of the testbench to consume. For example:

```python title="tb/stream/monitor.py"
from cocotb.triggers import RisingEdge
from forastero import BaseMonitor
from .transaction import StreamTransaction

class StreamMonitor(BaseMonitor):
    async def monitor(self, capture) -> None:
        while True:
            await RisingEdge(self.clk)
            if self.rst.value == 1:
                continue
            if self.io.get("valid", 1) and self.io.get("ready", 1):
                capture(StreamTransaction(data=self.io.get("data", 0)))
```

The `monitor` method can choose to operate in one of two ways. It may either (as
shown above) loop continuously observing the interface, or it can capture a
single packet and return control to the parent class that will then call it
again. In this example, when both `valid` and `ready` are high a transaction is
generated that captures the `data` signal.

The `capture` callback is provided as an argument to the `monitor` function,
behind the scenes this takes care of delivering the captured transaction to
different observers such as the scoreboard. For each transaction captured, this
`capture` callback should be executed.

Like drivers, monitors should be registered to the testbench as this performs
two tasks:

 * It registers the monitor with the testbench to ensure that it is idle before
   the test completes;
 * It attaches the monitor's captured transaction stream to the scoreboard
   allowing per-transaction comparisons to happen against a golden reference model.

For example:

```python title="tb/testbench.py"
from forastero import BaseBench, IORole
from .stream import StreamIO, StreamMonitor

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.INITIATOR)
        self.register("stream_mon",
                      StreamMonitor(self, stream_io, self.clk, self.rst))
```

!!! note

    The `stream_io` object in this case is created with an 'initiator' role as
    the DUT is driving the stream interface, as compared to the driver example
    above where the DUT receives the stream interface.

If, for any reason, you do not want a monitor to be attached to the scoreboard
then you may provide the argument `scoreboard=False` to the `self.register(...)`
call.

---

::: forastero.monitor.BaseMonitor
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
