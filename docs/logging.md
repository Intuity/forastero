Forastero builds on cocotb's
[SimLog](https://docs.cocotb.org/en/stable/_modules/cocotb/log.html) infrastructure,
adding hierarchical control over logging verbosity of each driver, monitor,
scoreboard, testcase, and other testbench component. The `SimLog` infrastructure
is in itself an extension of Python's built-in
[logging](https://docs.python.org/3/library/logging.html) library.

Forastero provides the following levels of hierarchy:

 * `tb` - the root of the logging hierarchy;
 * `tb.scoreboard` - used for messages emitted from the scoreboard;
 * `tb.scoreboard.channel.<X>` - used for messages emitted from a particular
   scoreboard channel;
 * `tb.driver.<X>` - used for messages emitted from a particular driver (when
   extending from [BaseDriver](./components/driver.md));
 * `tb.monitor.<X>` - used for messages emitted from a particular monitor (when
   extending from [BaseMonitor](./components/monitor.md));
 * `tb.io.<X>` - used for messages emitted from a particular I/O wrapper class
   (when extending from [BaseIO](./components/io.md));
 * `tb.test.<X>` - used for messages emitted from a particular testcase;
 * `tb.seq.<X>` - used for messages emitted from a specific sequence;
 * `tb.int` - is used for internal messages from the framework to do with the
   control and sequencing of tests:
   * `tb.int.orch` - used for log messages to do with testbench orchestration
     (e.g. used when draining different drivers and monitors at the end of a
     test);
   * `tb.int.seq` - used for internal messages related to sequence scheduling,
     arbitration, and execution.

These logging contexts are created using the `fork_log` method of
[BaseBench](./testbench.md). If you want to introduce custom layers of
hierarchy, then you should similarly call `fork_log` with your logging context
e.g.:

```python
@Testbench.testcase()
async def my_testcase(tb, log):
    my_sub_log = tb.fork_log("testcase", "my_testcase", "my_sub_log")
    my_sub_log.info("Hello!")
```

Logging verbosity is controlled hierarchically, for example the root log (`tb`)
can be set to `INFO` verbosity while a specific driver (e.g. `tb.driver.mydriver`)
can be set to `DEBUG` verbosity. This allows selective high-verbosity messages
to be shown in the log, while suppressing them from areas of no interest.

Hierarchical log verbosity is controlled via the test parameters file:

```json
{
    "verbosity": {
        "tb": "info",
        "tb.driver.mydriver": "debug",
        "tb.testcase.mytestcase": "warning"
    }
}
```

The verbosity control should always provide at least a `tb` root context, and
can then provide any number of refinements for specific log contexts. For each
context the value should map to one of the
[Python logging level names](https://docs.python.org/3/library/logging.html#logging-levels),
where the value is case-insensitive.
