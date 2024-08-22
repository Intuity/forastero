# Testcases

## Writing Testcases

cocotb provides the `@cocotb.test()` decorator to distinguish a Python function
as a test, Forastero replaces this with a decorator defined by the testbench
class. For example:

```python
from cocotb.log import SimLog
from ..testbench import Testbench

@Testbench.testcase()
async def smoke(tb : Testbench, log: SimLog):
    # ...
```

As shown above, `@cocotb.test()` is replaced by `@Testbench.testcase()` - this
performs all the same functions but replaces the `dut` argument that cocotb
normally provides with a pointer to an instance of `Testbench` instead and
provides a second argument called `log`. This decorator does provide some new
arguments:

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

The decorated testcase function is provided with two arguments by default:

 * `tb` - a reference to the testbench instance being used for this test;
 * `log` - a logging handler that is specialised to the testcase, for further
   details see the [logging](./logging.md) documentation.

## Testcase Parameters

Parameters can be used to vary the behaviour of a testcase, for example they can
be used to perform a sweep over different packet lengths injected into the DUT
without rewriting or adding extra testcases. A parameter is declared using the
`@Testbench.parameter("...")` decorator, default values can then be encoded as
keyword arguments in the function declaration. For example:

```python
from cocotb.log import SimLog
from ..testbench import Testbench

@Testbench.testcase()
@Testbench.parameter("num_packets")
@Testbench.parameter("packet_min_len")
@Testbench.parameter("packet_max_len")
async def inject_packets(tb : Testbench,
                         log: SimLog,
                         num_packets: int = 100,
                         packet_min_len: int = 1,
                         packet_max_len: int = 10):
    for _ in num_packets:
        pkt_len = tb.random.randint((packet_min_len, packet_max_len))
        # ...
```

Parameter values can then be controlled using the parameters JSON file that is
passed into the testbench using the `TEST_PARAMS` environment variable. This
can be done in two ways.

If multiple testcases declare and use the same parameter in the same way, then
the declaration in the parameters JSON file can use just the parameter name.
Alternatively if different testcases use the same parameter name for different
purposes, then the parameter value can be set using `<TESTCASE>.<PARAMETER>` as
the name - for example:

```json
{
    "testcases": {
        "inject_packets.num_packets": 250,
        "other_testcase.num_packets": 95,
        "packet_min_len": 5
    }
}
```

Parameter values are resolved using the following priority:

 1. `<TESTCASE>.<PARAMETER>` in the test parameters file;
 2. `<PARAMETER>` in the test parameters file;
 3. The default value provided as a keyword argument in the function declaration.

Therefore using the example above and considering the `inject_packets` testcase:

 * `num_packets` will be resolved as `250`;
 * `packet_min_len` will be resolved as `5`;
 * `packet_max_len` will retain its default value of `10`.
