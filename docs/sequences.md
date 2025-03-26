There are two competing objectives when it comes to testing a design:

 1. To utilise random stimulus as far as possible in order to avoid implicit
    assumptions being baked into testcases and hence failing to explore the
    "unknown-unknowns";

 2. To explore the entire state space of the DUT, in some cases reaching very
    deep sequential pathways that require very specific stimulus.

Forastero offers the concept of 'sequences' to help address both of these
objectives. A sequence can act in any way it likes, from providing entirely
random stimulus all the way to directing a very specific set of operations.
A testcase can schedule any number of sequences to be executed concurrently,
allowing different stimulus patterns to be overlayed on each other to create
complex interactions.

## Defining a Sequence

A sequence is defined using the `sequence` decorator, and this must wrap around
an `async def` function declaration:

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext

@forastero.sequence()
async def very_simple_seq(ctx: SeqContext):
    ...
```

A sequence must declare the drivers and monitors that it wishes to interact with,
this is achieved using the `requires` decorator:

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqProxy

from ..stream import StreamInitiator, StreamMonitor

@forastero.sequence()
@forastero.requires("stream_drv", StreamInitiator)
@forastero.requires("stream_mon", StreamMonitor)
async def very_simple_seq(ctx: SeqContext,
                          stream_drv: SeqProxy[StreamInitiator],
                          stream_mon: SeqProxy[StreamMonitor]):
    ...
```

!!! note

    The name of the driver/monitor used in the `requires` decorator is internal
    to the sequence, it does **not** relate to the name of the driver/monitor
    registered into the testbench. When a sequence is scheduled, the testcase
    must identify the driver and monitor that matches each requirement.

A sequence may also accept parameters in order to vary it's behaviour - in the
example below two arguments of `repetitions` and `data_width` are provided
that the sequence can then use to guide the transactions it produces:

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqProxy

from ..stream import StreamInitiator, StreamMonitor

@forastero.sequence()
@forastero.requires("stream_drv", StreamInitiator)
@forastero.requires("stream_mon", StreamMonitor)
async def very_simple_seq(ctx: SeqContext,
                          stream_drv: SeqProxy[StreamInitiator],
                          stream_mon: SeqProxy[StreamMonitor],
                          repetitions: int = 100,
                          data_width: int = 64):
    ...
```

## Locking

As sequences run, they can interact with any number of [drivers](./components/driver.md)
or [monitors](./components/monitor.md) to stimulate or observe the design. However,
at any one time any number of sequences may be attempting to enqueue stimulus
into the DUT and this creates a problem.

For example if sequence A produces entirely random stimulus while sequence B is
attempting to configure the DUT in a specific way, then sequence B could be
easily disrupted by sequence A and fail to achieve the desired state space.

To resolve this problem Forastero allows sequences to acquire locks that allow
them to take sole control of selected drivers and monitors for an arbitrary
period of the test.

When a lock is acquired on a driver, it allows the sequence the sole right to
`enqueue` transactions to that driver. If the `enqueue` function is called by
a sequence that doesn't hold the lock, an exception will always be raised.

When a lock is acquired on a monitor, it allows the sequence the sole right to
observe transactions being captured by that monitor - either via `subscribe` or
`wait_for`. If no locks are claimed on a monitor, then all active sequences can
observe transactions. If a sequence observes a monitor while the lock is held by
another sequence, then the sequence will not be notified of events while the lock
is held.

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqProxy

from ..stream import StreamInitiator, StreamTransaction

@forastero.sequence()
@forastero.requires("stream_a", StreamInitiator)
@forastero.requires("stream_b", StreamInitiator)
async def weird_traffic(ctx: SeqContext,
                        stream_a: SeqProxy[StreamInitiator],
                        stream_b: SeqProxy[StreamInitiator]):
    # Send a transaction to just stream A
    async with ctx.lock(stream_a):
        stream_a.enqueue(StreamTransaction(data=ctx.getrandbits(32)))
    # Send a transaction to just stream B
    async with ctx.lock(stream_b):
        stream_b.enqueue(StreamTransaction(data=ctx.getrandbits(32)))
    # Send a transaction to BOTH streams
    async with ctx.lock(stream_a, stream_b):
        stream_a.enqueue(StreamTransaction(data=ctx.getrandbits(32)))
        stream_b.enqueue(StreamTransaction(data=ctx.getrandbits(32)))
```

!!! note

    This example uses an asynchronous context manager (e.g. `async with`) to
    claim locks. Any locks claimed by the context are then automatically released
    once the program moves beyond the context (i.e. returns to the outer
    indentation level).

Sequences can also declare arbitrarily named locks that they can use to
co-ordinate with other sequences using the `requires` decorator but without
providing an expected type, for example this may be used to represent some state
of the design that is not directly exposed via the I/Os of the DUT.

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqLock, SeqProxy

from ..apb import ApbInitiator, ApbTransaction
from ..irq import IrqInitiator, IrqTransaction

@forastero.sequence()
@forastero.requires("cfg", ApbInitiator)
@forastero.requires("irq", IrqInitiator)
@forastero.requires("irq_config")
async def trigger_interrupt(ctx: SeqContext,
                            cfg: SeqProxy[ApbInitiator],
                            irq: SeqProxy[IrqInitiator],
                            irq_config: SeqLock):
    # Claim drivers and lock to avoid IRQ being re-configured
    async with ctx.lock(cfg, irq, irq_config):
        # Setup register block to handle IRQs
        cfg.enqueue(ApbTransaction(address=0x0, ...))
        cfg.enqueue(ApbTransaction(address=0x4, ...))
        # Release the APB lock
        # NOTE: This relies on other sequences respecting the irq_config lock
        ctx.release(cfg)
```

!!! warning

    Releasing a lock that a sequence doesn't hold will result in an exception
    being raised.

Sequences may not request more locks until they have released all previously
held locks, this means that nesting contexts (as shown below) is illegal and will
lead to an exception being raised:

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqLock, SeqProxy

from ..apb import ApbInitiator, ApbTransaction
from ..irq import IrqInitiator, IrqTransaction

@forastero.sequence()
@forastero.requires("cfg", ApbInitiator)
@forastero.requires("irq", IrqInitiator)
@forastero.requires("irq_config")
async def trigger_interrupt(ctx: SeqContext,
                            cfg: SeqProxy[ApbInitiator],
                            irq: SeqProxy[IrqInitiator],
                            irq_config: SeqLock):
    async with ctx.lock(cfg):
        async with ctx.lock(irq): # ILLEGAL!
            async with ctx.lock(irq_config): # ILLEGAL!
                ...
```

## Auto-Locking Sequences

Some simple sequences may only ever need to claim locks once and then will release
them all once the sequence completes. In such a scenario a sequence can be marked
as 'auto-locking' by providing `auto_lock=True` to the `sequence` decorator:

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqLock, SeqProxy

from ..apb import ApbInitiator, ApbTransaction
from ..irq import IrqInitiator, IrqTransaction

@forastero.sequence(auto_lock=True)
@forastero.requires("cfg", ApbInitiator)
@forastero.requires("irq", IrqInitiator)
@forastero.requires("irq_config")
async def my_auto_lock_seq(ctx: SeqContext,
                           cfg: SeqProxy[ApbInitiator],
                           irq: SeqProxy[IrqInitiator],
                           irq_config: SeqLock):
    # NOTE: The 'async with' is no longer needed!
    cfg.enqueue(ApbTransaction(address=0x0, ...))
    cfg.enqueue(ApbTransaction(address=0x4, ...))
    irq.enqueue(IrqTransaction(...))
```

## Scheduling Sequences

When using sequences the role of the testcase is to select the sequences that
need to be scheduled, provide references to the drivers and monitors, and specify
any parameter values. Sequences are scheduled using the `tb.schedule(...)`
function:

```python title="tb/testcases/streams.py"
from cocotb.log import SimLog

import forastero
from forastero.driver import DriverEvent
from forastero.sequence import SeqContext, SeqProxy

from ..stream import StreamInitiator, StreamTransaction
from ..testbench import Testbench

@forastero.sequence()
@forastero.requires("stream_drv", StreamInitiator)
async def random_traffic(ctx: SeqContext,
                         stream_drv: SeqProxy[StreamInitiator],
                         length: int = 1,
                         data_width: int = 32):
    for idx in range(length):
        async with ctx.lock(stream_drv):
            ctx.log.info(f"Driving packet {idx}")
            stream_drv.enqueue(StreamTransaction(data=ctx.random.getrandbits(data_width)))
            await stream_drv.wait_for(DriverEvent.PRE_DRIVE)

@Testbench.testcase()
async def stress_all_interfaces(tb: Testbench, log: SimLog):
    """Drive lots of random traffic on all stream interfaces"""
    for stream in (tb.stream_a, tb.stream_b, tb.stream_c):
        tb.schedule(random_traffic(stream_drv=stream, length=1000, data_width=64))
```

!!! note

    When the testcase schedules the sequence it must provide the right driver or
    monitor for each component required by the sequence, in this case the sequence
    requires `stream_drv` and the testcase is mapping this to `stream_a`,
    `stream_b`, and `stream_c` in turn.

Taking a closer look at the `schedule` call, there is a difference between the
arguments of the sequence function:

```python
async def random_traffic(ctx: SeqContext,
                         stream_drv: SeqProxy[StreamInitiator],
                         length: int = 1,
                         data_width: int = 32):
```

...and the `schedule` call:

```python
tb.schedule(random_traffic(stream_drv=stream, length=1000, data_width=64))
```

For those struggling to spot the difference, the `ctx` argument is missing from
the scheduling call. This is deliberate as the context is filled in by the
testbench as the sequence is scheduled, more details on the context object can
be found below.

## Sequence Context

Each sequence scheduled is provided with a unique instance of
[SeqContext](#forastero.sequence.SeqContext), which provides a number of useful
mechanisms:

 * `seq.log` provides a [logging context](./logging.md) that is unique to the
   sequence;
 * `seq.random` provides an instance of Python's
   [Random](https://docs.python.org/3/library/random.html) class that is seeded
   in such a way that a given sequence should be invariant run-to-run even if
   other sequence is altered;
 * `seq.lock` and `seq.release` allow a testcase to claim and release locks on
   drivers and monitors as well as arbitrary named locks;
 * `seq.ctx` and `seq.rst` provide access to the same clock and reset signals
   that the main testbench uses.

A sequence should always use the context for logging and random number generation
rather than accessing the root testbench directly.

## Sequence Arbitration

When more than one sequence is scheduled, the arbiter is responsible for deciding
which sequence is able to claim locks first - this is especially important when
sequences are in contention over shared locks.

The current arbitration implementation is based on random ordering of the queued
sequences (i.e. everything currently waiting on a `async with ctx.lock(...)` call).
Future improvements to Forastero will introduce more complex arbitration functions
that allow control over the balancing of different sequences.

## Randomised Sequence Arguments

When defining sequences it is good practice to make them reusable and provide
arguments to vary the stimulus that the sequence generates. In the sections
above it was shown how to declare normal arguments with static default values,
but Forastero also offers the possibility to randomise the values of the
arguments within simple constraints.

```python title="tb/sequences/sequence.py"
import forastero
from forastero.sequence import SeqContext, SeqProxy

from ..stream import StreamInitiator, StreamMonitor

@forastero.sequence()
@forastero.requires("stream_drv", StreamInitiator)
@forastero.requires("stream_mon", StreamMonitor)
@forastero.randarg("repetitions", range=(100, 300))
@forastero.randarg("data_mode", choices=("random", "zero", "one", "increment"))
async def rand_data_seq(ctx: SeqContext,
                        stream_drv: SeqProxy[StreamInitiator],
                        stream_mon: SeqProxy[StreamMonitor],
                        repetitions: int,
                        data_mode: str,
                        data_width: int = 64):
    ...
```

The example above defines three arguments to the sequence, of which two are
randomised:

 * `repetitions` will take a random value between 100 and 300 (inclusive);
 * `data_mode` will select a random string from `random`, `zero`, `one`, or
   `increment`.

The `data_width` argument is not randomised as this is expected to be matched to
a design constant (i.e. the bus width).

The `randarg` decorator always requires a variable name and exactly one randomisation
mode, selected from:

 * `range=(X, Y)` selects a random value in the range X to Y inclusive;
 * `bit_width=X` selects a random value over a bit width of X bits;
 * `choices=(X, Y, Z, ...)` makes a random choice from a restricted list of values.

Randomisation is performed at the point the sequence is scheduled, so code running
inside the sequence will see a fixed value. The log contains messages (at debug
verbosity) detailing the sequence and variables that was scheduled:

```bash
21.00ns DEBUG  tb.sequence.rand_data_seq[0]  Launching rand_data_seq[0] with variables: {'repetitions': 127, 'data_mode': 'one'}
```

The values and randomisation behaviour can also be overridden at the point the
sequence is scheduled, for example:

```python title="tb/testcases/streams.py"
@Testbench.testcase()
async def random_traffic(tb: Testbench, log: SimLog):
    # Schedule a fixed length burst of entirely random traffic
    tb.schedule(rand_data_seq(repetitions=10, data_mode="random"))
    # Schedule a burst between 30 and 60 transactions of zero or one traffic
    tb.schedule(rand_data_seq(repetitions_range=(30, 60),
                              data_mode_choices=("one", "zero")))
```

When providing an override:

 * `<X>=123` will fix the argument to a static value;
 * `<X>_range=(Y, Z)` will override the range randomisation between `Y` and `Z`;
 * `<X>_bit_width=Y` will override the bit-width randomisation to `Y` bits;
 * `<X>_choices=(A, B, C)` will override the choices to be selected from to be
   one of `A`, `B`, or `C`.

---

::: forastero.sequence.SeqLock
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.sequence.SeqProxy
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.sequence.SeqArbiter
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.sequence.SeqContextEvent
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.sequence.SeqContext
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.sequence.BaseSequence
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
