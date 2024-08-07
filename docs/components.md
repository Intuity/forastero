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

## Interfaces

[Drivers](./classes/driver.md) and [Monitors](./classes/monitor.md) are most
useful when interacting with bus protocols where the interface may not only
transport data but also sideband signals (e.g. transaction IDs) and qualifiers
(e.g. valid/ready). To support this, Forastero offers `BaseIO` which can be
extended to define a grouping of signals that are common to your DUTs interfaces.

For example, imagine that our DUT has two interfaces - one incoming stream and
one outgoing stream. These stream interfaces carry both data along with valid
and ready qualifiers to ensure correct data transport...

```sv
module buffer #(
      input  logic        i_clk
    , input  logic        i_rst
    // Upstream
    , input  logic [31:0] i_us_data
    , input  logic        i_us_valid
    , output logic        o_us_ready
    // Downstream
    , output logic [31:0] o_us_data
    , output logic        o_us_valid
    , input  logic        i_us_ready
);
```

We can declare a matching Forastero I/O definition to wrap up the `data`,
`valid`, and `ready` signals into one convenient object:

```python
from forastero import BaseIO, IORole

class StreamIO(BaseIO):
    def __init__(
        self,
        dut: HierarchyObject,
        name: str | None,
        role: IORole,
        io_style: Callable[[str | None, str, IORole, IORole], str] | None = None,
    ) -> None:
        super().__init__(
            dut=dut,
            name=name,
            role=role,
            init_sigs=["data", "valid"],
            resp_sigs=["ready"],
            io_style=io_style,
        )
```

What's going on here then?

 * `StreamIO` extends from `BaseIO` - this is expected by `BaseDriver` and
   `BaseMonitor` and they will raise an error if this is not the case
 * The constructor is provided with
   * `dut` - a pointer to the top level of your DUT
   * `name` - the common name of the bus, or `None` if one is not used;
   * `role` - the "orientation" of the bus that is being referenced, for example
     if a stream interface is passing out of a block this makes the block an
     'initiator' (`role=IORole.INITIATOR`) while if a stream interface is passing
     into a block then this makes the block a 'responder' (`role=IORole.RESPONDER`)
   * `init_sigs` - a list of signals that are driven by the initator of an
     interface, in this case the `data` and the `valid` qualifier
   * `resp_sigs` - a list of signals that are driven by the responder to an
     interface, in this case this is just the `ready` signal
 * `io_style` - how components of the interface are named, see the section below
   for more details.

In our testbench we can then wrap the upstream and downstream interfaces of the
DUT very easily:

```python
from forastero import BaseBench, IORole

from .stream.io import StreamIO

class Testbench(BaseBench):
    def __init__(self, dut):
        # ...
        us_io = StreamIO(dut=dut, name="us", role=IORole.RESPONDER)
        ds_io = StreamIO(dut=dut, name="ds", role=IORole.INITIATOR)
```

!!! warning

    The `role` argument to classes derived from `BaseIO` refers to the role of
    the DUT's interface, not to the role the testbench plays!

### IO Naming Style

When using `BaseIO`, its default behaviour is to:

 * Expect that inputs are prefixed with `i_` and outputs with `o_`
 * The prefix is followed by the bus name (e.g. `i_us_`)
 * A final segment is included for the component name (e.g. `i_us_data`)

Under the hood this behaviour is defined by the `io_prefix_style`, but this can
be overridden either globally or on a case-by-case basis.

An interface naming style is declared by a function that takes four arguments
and returns a string:

 * `bus` - name of the bus as a string or `None` if unused
 * `component` - name of the interface component as a string
 * `role_bus` - role of the entire bus from `IORole` (e.g. `IORole.INITIATOR`)
 * `role_comp` - role of the specific component from `IORole`

The example below shows the implementation of `io_prefix_style`:

```python
def io_prefix_style(bus: str | None, component: str, role_bus: IORole, role_comp: IORole) -> str:
    mapping = {
        (IORole.INITIATOR, IORole.INITIATOR): "o",
        (IORole.INITIATOR, IORole.RESPONDER): "i",
        (IORole.RESPONDER, IORole.INITIATOR): "i",
        (IORole.RESPONDER, IORole.RESPONDER): "o",
    }
    full_name = f"{mapping[role_bus, role_comp]}"
    if bus is not None:
        full_name += f"_{bus}"
    return f"{full_name}_{component}"
```

If you define a custom naming style, this can be used when instancing a class
that inherits from `BaseIO`:

```python
def my_io_style(bus: str | None, component: str, role_bus: IORole, role_comp: IORole) -> str:
    # ...

class Testbench(BaseBench):
    def __init__(self, dut):
        us_io = StreamIO(
            dut=dut, name="us", role=IORole.RESPONDER, io_style=my_io_style
        )
```

Or, the style can be globally overridden:

```python
from forastero import BaseIO

def my_io_style(bus: str | None, component: str, role_bus: IORole, role_comp: IORole) -> str:
    # ...

BaseIO.DEFAULT_IO_STYLE = my_io_style

class Testbench(BaseBench):
    def __init__(self, dut):
        us_io = StreamIO(dut=dut, name="us", role=IORole.RESPONDER)
```

!!! note

    Three I/O styles are provided with Forastero, the first (and default) is
    `io_prefix_style` where signals are named `i/o_<BUS>_<COMPONENT>` but there
    is also `io_suffix_style`, where the `i/o` is moved to the end of the signal
    name `<BUS>_<COMPONENT>_i/o`, and `io_plain_style` where there is no `i/o`
    prefix or suffix and signals are simply named `<BUS>_<COMPONENT>`.

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

When `self.register(...)` is called it will register the monitor against the
scoreboard and queue captured transactions into a dedicated channel (unless
`scoreboard=False` is set). If no other parameters are provided then the
scoreboard will create a simpple channel.

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
