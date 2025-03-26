[Drivers](./driver.md) and [Monitors](./monitor.md) are most useful when
interacting with bus protocols where the interface may not only transport data
but also sideband signals (e.g. transaction IDs) and qualifiers (e.g. valid/ready).
To support this, Forastero offers `BaseIO` which can be extended to define a
grouping of signals that are common to your DUTs interfaces.

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

---

::: forastero.io.IORole
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

---

::: forastero.io.BaseIO
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
