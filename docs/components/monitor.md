Monitors observe signals wiggling on the boundary of the design and capture the
state into [transaction](./transaction.md) objects that can be scoreboarded by
the testbench against a model.

## Defining a Monitor

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
            if self.rst.value == self.tb.rst_active_value:
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

## Registering Monitors

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

## Monitor Events

As signal states are observed by a monitor and converted into transactions, events
are emitted to allow observers such as models or scoreboards to act upon it:
There is only one type of event defined:

 * [CAPTURE](#forastero.monitor.MonitorEvent.CAPTURE) - emitted when a transaction
   is captured by a monitor from the DUT's signal state;

### Subscribing to Events

A callback can be registered again any event, this may either be a synchronous
or asynchronous method and will be called every time that the given event occurs:

```python title="tb/testbench.py"
from forastero.monitor import MonitorEvent

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.INITIATOR)
        self.register("stream_mon",
                      StreamMonitor(self, stream_io, self.clk, self.rst))
        self.stream_mon.subscribe(MonitorEvent.CAPTURE, self.stream_capture)

    async def stream_capture(self,
                             monitor: StreamMonitor,
                             event: MonitorEvent,
                             obj: StreamTransaction):
        # ...do something...
```

### Waiting for Events

A test can wait for a specific monitor event to occur using the `wait_for` method,
this will block until the event happens and then return the transaction that
caused the event:

```python title="tb/testcases/my_testcase.py"
from forastero.monitor import MonitorEvent

@Testbench.testcase()
async def my_testcase(tb: Testbench, log: SimLog):
    for idx in range(10):
        obj = await tb.stream_mon.wait_for(MonitorEvent.CAPTURE)
        assert obj.data == 0x1234_0000 + idx
```

## Filtering Transactions

Monitors are intended to be stateless and only meant to observe the DUT and not
model its behaviour, in some cases this may mean that the transactions produced
will contain data that disagrees with a model and hence would cause miscomparisons
in the scoreboard. There are two ways to deal with this:

### Non-Compared Fields

[Transaction](./transaction.md) objects are an extension of Python's `dataclasses`
library, which provides a number of methods for controlling how comparisons are
made. One particularly useful feature is the `compare=False` switch when declaring
dataclass fields:

```python title="tb/mapped/transaction.py"
import dataclasses

@dataclasses.dataclass(kw_only=True)
class MappedRequest(BaseTransaction):
    # ...other fields...
    id : int = dataclasses.field(default=0, compare=False)
```

When comparisons of different instances of `MappedRequest` are made, fields marked
with `compare=False` are ignored. For example, the `timestamp` field of all objects
inheriting from `BaseTransaction` is marked as `compare=False` which allows a model
to generate reference transactions at different time compared to when a monitor
captures the event from the DUT.

### Filtering

When registering a monitor against the scoreboard, a function may be provided
that can modify or even entirely drop captured transactions. This can be useful
when transaction fields are not relevant in all comparisons.


```python title="tb/testbench.py"
class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        self.register("mapped_req_mon",
                      MappedRequestMonitor(
                          self,
                          MappedRequestIO(dut, "map_req", IORole.INITIATOR),
                          self.clk,
                          self.rst,
                      ),
                      sb_filter=self.filter_mapped_req_mon)
        self.mapped_req_mon.subscribe(MonitorEvent.CAPTURE, self.mapped_capture)

    def filter_mapped_req_mon(self,
                          monitor: MappedMonitor,
                          event: MonitorEvent,
                          obj: MappedTransaction) -> MappedTransaction | None:
        # If this is an access to address 0, drop the access
        if obj.address == 0:
            return None
        # If this is a read transaction, blank out the write data
        if obj.access is MappedAccess.READ:
            obj.data = 0
        return obj
```

!!! note

    Returning `None` from a filter function signals that the transaction should
    be ignored by the scoreboard.

---

::: forastero.monitor.BaseMonitor
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.monitor.MonitorEvent
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
