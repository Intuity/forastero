Most testbenches require two types of component to operate:

 * Drivers stimulate interfaces on the design according to the implementation's
   signalling protocols. They convert transactions from the representation used
   by the testbench into the state of the different signals on the boundary of
   the design.

 * Monitors act in the opposite way to drivers, monitoring the signals wiggling
   on the boundary of the design and capturing those into transactions that the
   testbench analyses.

Different interfaces will require custom drivers and monitors, but there is a
common core of shared functionality - this is why Forastero provides two base
classes [BaseDriver](./classes/driver.md) and [BaseMonitor](./classes/monitor.md).

## Transactions

Forastero expects drivers and monitors to consume or produce a standard form of
transaction that is based on Python's
[dataclasses](https://docs.python.org/3/library/dataclasses.html) library. A
custom base class ([BaseTransaction](./classes/transaction.md)) is provided that
helps Forastero interact with these components.

For example, a transaction for driving requests on an address mapped interface
to a memory may look something like the following:

```python title="tb/mapped/transaction.py"
import dataclasses
from enum import IntEnum, auto

from forastero import BaseTransaction

class MappedAccess(IntEnum):
    READ  = auto()
    WRITE = auto()

@dataclasses.dataclass(kw_only=True)
class MappedRequest(BaseTransaction):
    address : int = 0
    access  : MappedAccess = MappedAccess.READ
    data    : int = 0
```

The `MappedRequest` transaction is decorated by `dataclass` to mark it as a
dataclass object (see the Python documentation for more details), but importantly
also inherits from [BaseTransaction](./classes/transaction.md). This base class
provides a standard entry called `timestamp` that is used to capture when the
transaction was submitted to or captured from the design, it is excluded from
comparisons and exists primarily for debug.

## Drivers

Drivers inherit from [BaseDriver](classes/driver.md) and must implement the
`drive` method to convert a transaction object into the implementation's
signalling protocol. For example:

```python title="tb/stream/transaction.py"
from forastero import BaseTransaction

@dataclass(kw_only=True)
class StreamTransaction(BaseTransaction):
    data: int = 0
```

```python title="tb/stream/initiator.py"
from cocotb.triggers import RisingEdge
from forastero import BaseDriver
from .transaction import StreamTransaction

class StreamInitiator(BaseDriver):
    async def drive(self, obj: StreamTransaction) -> None:
        self.io.set("data", obj.data)
        self.io.set("valid", 1)
        while True:
            await RisingEdge(self.clk)
            if self.io.get("ready", 1):
                break
        self.io.set("valid", 0)
```

The `drive` method is called whenever a transaction is queued onto the driver by
the testcase. It should setup the stimulus, wait until it is accepted by the
design, then return the stimulus to a neutral state. In the example above, flow
is controlled by `valid` and `ready` signals of the interface - `valid` is
setup to qualify `data`, then at least one cycle must pass before data is
accepted when both `valid` and `ready` are high together.

Drivers must be registered to the testbench, this ensures that each test waits
until all stimulus has been fed into the design before the test is allowed to
complete.

```python title="tb/testbench.py"
from forastero import BaseBench, IORole
from .stream import StreamInitiator, StreamIO

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.RESPONDER)
        self.register("stream_init",
                      StreamInitiator(self, stream_io, self.clk, self.rst))
```

To highlight a few important points:

 * The stream interface is wrapped up in a `StreamIO` object (this inherits
   from [BaseIO](./classes/io.md)), that assumes signals of `i_stream_data`,
   `i_stream_valid`, and `o_stream_ready` (meaning the DUT is taking the role
   of an interface 'responder');
 * An instance of `StreamInitiator` is created, providing a handle to the
   testbench, the `StreamIO` object, and the associated clock and reset signals;
 * The instance of `StreamInitiator` is registered to the testbench using the
   name `stream_init`.

Testcases may queue transactions onto a driver using the `enqueue` method - for
example:

```python title="tb/testcases/random.py"
from cocotb.log import SimLog

from ..stream import StreamTransaction
from ..testbench import Testbench

@Testbench.testcase()
async def random(tb: Testbench, log: SimLog):
    for _ in range(100):
        tb.stream_init.enqueue(StreamTransaction(data=tb.random.getrandbits(32)))
```

Note that `tb.stream_init` refers to the instance of `StreamInitiator` that was
registered onto the testbench in the previous example. The `for` loop then
generates a number of `StreamTransaction` objects carrying random data.

Drivers can return an event to allow a test or sequence to determine when a
particular transaction reaches a pre or post-drive state. When `wait_for` is
provided, the `enqueue` function will return a cocotb `Event`, and this can be
awaited:

```python title="tb/testcases/random.py"
from cocotb.log import SimLog

from forastero.driver import DriverEvent

from ..stream import StreamTransaction
from ..testbench import Testbench

@Testbench.testcase()
async def random(tb: Testbench, log: SimLog):
    for _ in range(100):
        await tb.stream_init.enqueue(
            StreamTransaction(data=tb.random.getrandbits(32)),
            wait_for=DriverEvent.POST_DRIVE
        ).wait()
```

## Monitors

Monitors inherit from [BaseMonitor](./classes/monitor.md) and must implement the
`monitor` method, that observe signals on or within the DUT and generate
transactions for other parts of the testbench to consume. For example:

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

### Scoreboard Channel Types

When a monitor is attached onto the scoreboard (i.e. `self.register(...)` is
called with `scoreboard=True`, which is the default behaviour) it is normally
registered as a simple channel.

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
                      scoreboard_queues=["a", "b", "c"])

    def model_arbiter_src_b(self):
        self.scoreboard.channels["arb_output_mon"].push_reference(
            "b", StreamTransaction(...)
        )
```

### Scoreboard Channel Timeouts

While each registered testcase can provide a timeout, this in many cases may be
set at a very high time to cope with complex, long running testcases. To provide
a finer granularity of timeout control, timeouts may be configured specifically
to scoreboard channels that specify how long it is acceptable for a transaction
to sit at the front of the monitor's queue before the scoreboard matches it to
a reference transaction. There are two key parameters to `self.register(...)`:

 * `scoreboard_timeout_ns` - the maximum acceptable age a transaction may be at
   the front of the monitor's channel. The age is determined by substracting the
   transaction's `timestamp` field (a default property of `BaseTransaction`)
   from the current simulation time.

 * `scoreboard_polling_ns` - the frequency with which to check the front of the
   scoreboard's monitor queue, this defaults to `100 ns`.

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
                      scoreboard_timeout_ns=10)
```

## Logging

Both `BaseDriver` and `BaseMonitor` inherit from `Component`, and this root class
provides a number of utility features. One of the most useful is a hierarchical
log specific to the driver or monitor.

 * All drivers will be given a logging context of `tb.driver.<NAME>`;
 * All monitors will be given a logging context of `tb.monitor.<NAME>`.

These logs can be accessed using `self.log`, for example:

```python title="tb/stream/monitor.py"
class StreamMonitor(BaseMonitor):
    async def monitor(self, capture) -> None:
        while True:
            await RisingEdge(self.clk)
            if self.rst.value == 1:
                continue
            if self.io.get("valid", 1) and self.io.get("ready", 1):
                self.log.debug("Hello! I saw a transaction!")
                capture(StreamTransaction(data=self.io.get("data", 0)))
```

In the simulation log, you will see the logging context appear along with the
timestamp, verbosity, and log message - for example:

```
1229.00ns INFO  tb.driver.driver_a    Starting to send transaction
1230.00ns INFO  tb.driver.driver_b    Finished sending a transaction
1231.00ns INFO  tb.monitor.monitor_a  Hello! I saw a transaction!
```

More details on [logging can be found here](./logging.md).
