Most testbenches require two types of component to operate:

 * [Drivers](./driver.md) stimulate interfaces on the design according to the
   implementation's signalling protocols. They convert [transactions](./transaction.md)
   from the representation used by the testbench into the state of the different
   signals on the boundary of the design.

 * [Monitors](./monitor.md) act in the opposite way to drivers, monitoring the
   signals wiggling on the boundary of the design and capturing those into
   transactions that the testbench analyses.

Different interfaces will require custom drivers and monitors, but there is a
common core of shared functionality - this is why Forastero provides two base
classes [BaseDriver](./driver.md) and [BaseMonitor](./monitor.md).

## Events

The [Component](#forastero.component.Component) class inherits from the
[EventEmitter](#forastero.event.EventEmitter) class, which supports the publishing
of and subscription to events. This mechanism can be used to drive models,
co-ordinate stimulus, or generally observe the state of monitors and drivers.

The documentation for [Drivers](./driver.md#events) and [Monitors](./monitor.md#events)
will go further into how these mechanisms can be used.

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
            if self.rst.value == self.tb.rst_active_value:
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

More details on [logging can be found here](../logging.md).

---

::: forastero.component.Component
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false

::: forastero.event.EventEmitter
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
