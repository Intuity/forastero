Drivers are used to stimulate interfaces on the design according to the
implementation's signalling protocols. They convert [transactions](./transaction.md)
from the representation used by the testbench into the state of the different
signals on the boundary of the design.

## Defining a Driver

Drivers inherit from [BaseDriver](#forastero.driver.BaseDriver) and must
implement the `drive` method to convert a transaction object into the
implementation's signalling protocol.

Drivers depend on a [transaction](./transaction.md) class being defined, here a
simple stream data object is defined:

```python title="tb/stream/transaction.py"
from forastero import BaseTransaction

@dataclass(kw_only=True)
class StreamTransaction(BaseTransaction):
    data: int = 0
```

The driver's `drive` method consumes these `StreamTransaction` objects and
converts them into signal state to the DUT:

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

## Registering Drivers

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
   from [BaseIO](./io.md)), that assumes signals of `i_stream_data`,
   `i_stream_valid`, and `o_stream_ready` (meaning the DUT is taking the role
   of an interface 'responder');
 * An instance of `StreamInitiator` is created, providing a handle to the
   testbench, the `StreamIO` object, and the associated clock and reset signals;
 * The instance of `StreamInitiator` is registered to the testbench using the
   name `stream_init`.

## Driver Events

As transactions progress through a driver, events are emitted to allow observers
such as models or stimulus generation to track its progress. There are 3 different
events defined:

 * [ENQUEUE](#forastero.driver.DriverEvent.ENQUEUE) - emitted when a transaction
   is enqueued into a driver by a test or sequence, this may happen long before
   the transaction is driven into the DUT;
 * [PRE_DRIVE](#forastero.driver.DriverEvent.PRE_DRIVE) - emitted just prior to a
   queued transaction being driven into the DUT;
 * [POST_DRIVE](#forastero.driver.DriverEvent.POST_DRIVE) - emitted just after a
   queued transaction is driven into the DUT;

A callback can be registered against any event, this may either be a synchronous
or asynchronous method:

```python
from forastero.driver import DriverEvent

class Testbench(BaseBench):
    def __init__(self, dut) -> None:
        super().__init__(dut, clk=dut.i_clk, rst=dut.i_rst)
        stream_io = StreamIO(dut, "stream", IORole.RESPONDER)
        self.register("stream_init",
                      StreamInitiator(self, stream_io, self.clk, self.rst))
        self.stream_init.subscribe(DriverEvent.PRE_DRIVE, self.stream_pre_drive)
        self.stream_init.subscribe(DriverEvent.POST_DRIVE, self.stream_post_drive)

    def stream_pre_drive(self, driver, event, obj):
        self.info(f"Driver is about to drive object: {obj}")

    async def stream_post_drive(self, driver, event, obj):
        self.info(f"Driver has just driven object: {obj}")
        await ClockCycles(tb.clk, 10)
        # ...generate some stimulus...
```

## Generating Stimulus

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
registered onto the testbench in the Pvious example. The `for` loop then
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

---

::: forastero.driver.BaseDriver
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.driver.DriverEvent
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
