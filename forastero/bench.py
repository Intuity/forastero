# Copyright 2023, Peter Birch, mailto:peter@lightlogic.co.uk
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import functools
import json
import logging
import os
import random
import traceback
from collections import defaultdict
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, ClassVar

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject, ModifiableObject
from cocotb.log import SimLog, SimLogFormatter, SimTimeContextFilter
from cocotb.result import SimTimeoutError
from cocotb.task import Task
from cocotb.triggers import ClockCycles, Event, with_timeout

from .component import Component
from .driver import BaseDriver
from .io import IORole
from .monitor import BaseMonitor
from .scoreboard import DrainPolicy, Scoreboard
from .sequence import BaseSequence, SeqArbiter


def strtobool(val: str) -> bool:
    lval = val.strip().lower()
    if lval in (truthy := ("y", "yes", "t", "true", "on", "1")):
        return True
    elif lval in (falsey := ("n", "no", "f", "false", "off", "0")):
        return False
    else:
        raise ValueError(f"Invalid bool `{val}`, specify using one of `{truthy}` or `{falsey}`")


class BaseBench:
    """
    Base class for a Forastero testbench

    :param dut:        Handle to the DUT, provided by cocotb
    :param clk:        Handle to the primary clock signal
    :param rst:        Handle to the primary reset signal
    :param clk_drive:  Whether the primary clock signal should be driven
    :param clk_period: Tick period for the primary clock
    :param clk_units:  Units of the primary clock's period
    """

    TEST_REQ_PARAMS: ClassVar[dict[Any, list[tuple[str, Callable[[str], Any]]]]] = defaultdict(list)
    PARAM_FILE_PATH: ClassVar[str] = os.environ.get("TEST_PARAMS", None)
    PARAM_DEFAULTS: ClassVar[dict[str, Any]] = {
        # Random seed
        "seed": 0,
        # Hierarchical logging control
        # NOTE: 'tb' is the log hierarchy root
        "verbosity": {
            "tb": "info",
        },
        # Enable profiling by providing a path
        "profiling": None,
        # Enable fast failure
        "fail_fast": (os.environ.get("FAIL_FAST", "no").lower() == "yes"),
        # Postmortem (activate a Python breakpoint after a failure)
        "postmortem": False,
        # Testcase parameters
        "testcases": {},
    }

    def __init__(
        self,
        dut: HierarchyObject,
        clk: ModifiableObject | None = None,
        rst: ModifiableObject | None = None,
        clk_drive: bool = True,
        clk_period: float = 1,
        clk_units: str = "ns",
    ) -> None:
        # Hold a pointer to the DUT
        self.dut = dut
        # Promote clock & reset
        self.clk = clk
        self.rst = rst
        # Clock driving
        self.clk_drive = clk_drive
        self.clk_period = clk_period
        self.clk_units = clk_units
        # Alias logging methods
        self.log = SimLog("tb")
        self.debug = self.log.debug
        self.info = self.log.info
        self.warning = self.log.warning
        self.error = self.log.error
        # Tee log into a file with timestamping
        log_fh = logging.FileHandler(Path.cwd() / "sim.log")
        log_fh.addFilter(SimTimeContextFilter())
        log_fh.setFormatter(SimLogFormatter())
        self.log.addHandler(log_fh)
        # Set verbosity at all specified hierarchy levels
        for hierarchy, verbosity in self.get_parameter("verbosity").items():
            logging.getLogger(hierarchy).setLevel(getattr(logging, verbosity.upper()))
        # Create a child log for orchestration
        # NOTE: This should really only be used by internal testbench processes
        self._orch_log = self.fork_log("int", "orch")
        # Create a scoreboard
        self.scoreboard = Scoreboard(
            tb=self,
            fail_fast=self.get_parameter("fail_fast", False),
            postmortem=self.get_parameter("postmortem", False),
        )
        # Track components
        self._components = {}
        self._processes = {}
        self._teardown = []
        # Random seeding
        self.seed = int(self.get_parameter("seed", 0))
        self.info(f"Bench initialised with random seed {self.seed}")
        self.random = random.Random(self.seed)
        # Sequence handling
        self._arbiter = SeqArbiter(self.fork_log("int", "seq"), self.random)
        self._sequences = []
        # Events
        self.evt_ready = Event()

    def fork_log(self, *scope: str) -> SimLog:
        """
        Create a new descedent of the root simulation log with a given context.

        :param *scope: A particular scope as a list of strings
        """
        if not scope:
            return self.log
        else:
            return self.log.getChild(".".join(scope))

    @classmethod
    @functools.cache
    def parse_parameters(cls) -> dict[str, Any]:
        parameters = cls.PARAM_DEFAULTS.copy()
        if cls.PARAM_FILE_PATH is None:
            logging.warning("No parameter file provided")
            return parameters
        path = Path(cls.PARAM_FILE_PATH)
        assert path.exists(), f"Parameter file does not exist: {path}"
        with path.open("r", encoding="utf-8") as fh:
            for key, value in json.load(fh).items():
                parameters[key.lower().strip()] = value
        return parameters

    @classmethod
    def get_parameter(cls, name: str, default: Any = None) -> Any:
        """
        Read back a parameter passed in from the outside world.

        :param name:    Name of the parameter to read
        :param default: Default value to return if parameter not defined
        :returns:       Value of the parameter or the default
        """
        return cls.parse_parameters().get(name.strip().lower(), default)

    async def ready(self) -> None:
        """Blocks until reset has completed"""
        await self.evt_ready.wait()
        self.evt_ready.clear()

    async def initialise(self) -> None:
        """Initialise the DUT's I/O"""
        self.rst.value = 1
        for comp in self._components.values():
            comp.io.initialise(IORole.opposite(comp.io.role))

    async def reset(self, init=True, wait_during=20, wait_after=1) -> None:
        """
        Reset the DUT.

        :param init:        Initialise the DUT's I/O
        :param wait_during: Clock cycles to hold reset active for (defaults to 20)
        :param wait_after:  Clock cycles to wait after lowering reset (defaults to 1)
        """
        # Drive reset high
        self.rst.value = 1
        # Initialise I/O
        if init:
            await self.initialise()
        # Wait before dropping reset
        if wait_during > 0:
            await ClockCycles(self.clk, wait_during)
        # Drop reset
        self.rst.value = 0
        # Wait for a bit
        if wait_after > 0:
            self.info(f"Waiting for {wait_after} cycles")
            await ClockCycles(self.clk, wait_after)

    def __getattr__(self, key: str) -> Any:
        """Pass through accesses to signals on the DUT.

        :param key: Name of the attribute
        :returns:   Resolved object
        """
        try:
            return getattr(super(), key)
        except Exception:
            return getattr(self.dut, key)

    def register(
        self,
        name: str,
        comp_or_coro: Component | Coroutine = None,
        scoreboard: bool = True,
        sb_queues: list[str] | tuple[str] | None = None,
        sb_filter: Callable | None = None,
        sb_timeout_ns: int | None = None,
        sb_polling_ns: int | None = None,
        sb_drain_policy: DrainPolicy | None = None,
        sb_match_window: int | None = None,
        **kwds,
    ) -> Component | Coroutine:
        """
        Register a driver, monitor, or coroutine with the testbench. Drivers and
        monitors must be provided a name and their random seeding will be setup
        from the testbench's random instance. Monitors will be registered with
        the scoreboard unless explicitly requested. Coroutines must also be named
        and are required to complete before the test will shutdown.

        :param name:            Name of the component or coroutine
        :param comp_or_coro:    Component instance or coroutine
        :param scoreboard:      Only applies to monitors, controls whether it is
                                registered with the scoreboard
        :param sb_queues:       A list of named queues used when a funnel type
                                scoreboard channel is required
        :param sb_filter:       A function that can filter or modify items
                                recorded by the monitor before they are passed
                                to the scoreboard
        :param sb_timeout_ns:   Optional timeout to allow for a object sat at the
                                front of the monitor queue to remain unmatched
                                (in nanoseconds, a value of None disables the
                                timeout mechanism)
        :param sb_polling_ns:   How frequently to poll to check for unmatched
                                items stuck in the monitor queue in nanoseconds
                                (defaults to 100 ns)
        :param sb_drain_policy: Specify how the handle should handle draining and
                                which queues should be considered when blocking
                                testcase shutdown
        :param sb_match_window: Where precise ordering of expected transactions
                                is not known, a positive integer matching window
                                can be used to match any of the next N transactions
                                in the reference queue (where N is set by
                                match_window)
        """
        # Allow either sb_ or scoreboard_ prefixes to arguments (back compatibility)
        sb_args = {
            "queues": sb_queues,
            "filter": sb_filter,
            "timeout_ns": sb_timeout_ns,
            "polling_ns": sb_polling_ns,
            "drain_policy": sb_drain_policy,
            "match_window": sb_match_window,
        }

        for key, value in sb_args.items():
            if (full_key := f"scoreboard_{key}") in kwds:
                assert value is None, f"Both sb_{key} and {full_key} specified"
                sb_args[key] = kwds.pop(full_key)

        assert not kwds, "Unexpected arguments: " + ", ".join(map(str, kwds.keys()))

        # Setup default argument values
        if sb_args["polling_ns"] is None:
            sb_args["polling_ns"] = 100
        if sb_args["drain_policy"] is None:
            sb_args["drain_policy"] = DrainPolicy.MON_AND_REF
        if sb_args["match_window"] is None:
            sb_args["match_window"] = 1

        assert isinstance(name, str), f"Name must be a string '{name}'"

        # Register a coroutine
        if asyncio.iscoroutine(comp_or_coro):
            assert name not in self._processes, f"Process known for '{name}'"
            task = cocotb.start_soon(comp_or_coro)
            self._processes[name] = task

        # Register a component (i.e. monitor or driver)
        elif isinstance(comp_or_coro, Component):
            assert name not in self._components, f"Component known for '{name}'"
            self._components[name] = comp_or_coro
            comp_or_coro.name = name
            setattr(self, name, comp_or_coro)
            comp_or_coro.seed(self.random)
            if scoreboard and isinstance(comp_or_coro, BaseMonitor):
                self.scoreboard.attach(
                    comp_or_coro,
                    filter_fn=sb_args["filter"],
                    queues=sb_args["queues"],
                    timeout_ns=sb_args["timeout_ns"],
                    polling_ns=sb_args["polling_ns"],
                    drain_policy=sb_args["drain_policy"],
                    match_window=sb_args["match_window"],
                )

        # Unknown type
        else:
            raise TypeError(f"Unsupported object: {comp_or_coro}")

        # Return the registered item to allow chaining
        return comp_or_coro

    def schedule(
        self,
        sequence: tuple[
            BaseSequence,
            Callable[[SimLog, random.Random, SeqArbiter, ModifiableObject, ModifiableObject], None],
        ],
        blocking: bool = True,
    ) -> Task:
        """
        Schedule a sequence to execute as part of a testcase.

        :param sequence: The sequence to schedule
        :param blocking: Whether the sequence must complete before the test is
                         allowed to finish
        :returns:        The scheduled task
        """
        seq_def, seq_inner = sequence
        task = cocotb.start_soon(
            seq_inner(
                self.fork_log("seq"),
                self.random,
                self._arbiter,
                self.clk,
                self.rst,
            )
        )
        if blocking:
            self._sequences.append((seq_def, task))
        return task

    def add_teardown(self, coro: Coroutine) -> None:
        """
        Register a coroutine to be executed after the shutdown loops have all
        completed, can be used to check final conditions.

        :param coro: Coroutine to register
        """
        assert asyncio.iscoroutine(coro), "Only coroutines may be added to teardown"
        self._teardown.append(coro)

    async def close_down(self, loops: int = 2, delay: int = 100) -> None:
        """
        Wait for drivers, monitors, and the scoreboard to drain to ensure that
        the test has completed.

        :param loops: Number of repetitions of the shutdown sequence to run
        :param delay: Number of clock cycles to wait between shutdown loops
        """
        # Filter drivers and monitors into separate lists
        drivers, monitors = [], []
        for comp in self._components.values():
            if not comp.blocking:
                continue
            [monitors, drivers][isinstance(comp, BaseDriver)].append(comp)
        # Check for consistent idleness
        for loop_idx in range(loops):
            # All drivers and monitors should be idle
            self._orch_log.info(f"Shutdown loop ({loop_idx+1}/{loops})")
            # Wait for sequences to complete
            self._orch_log.debug(f"Waiting for {len(self._sequences)} sequences to complete")
            for seq_def, seq_task in self._sequences:
                self._orch_log.debug(f"Waiting for sequence {seq_def.name}")
                await seq_task
            # Wait for minimum delay
            self._orch_log.debug("Waiting for minimum delay")
            await ClockCycles(self.clk, delay)
            # Wait for all drivers to return to idle
            for driver in drivers:
                self._orch_log.debug(f"Waiting for driver '{driver.name}' to go idle")
                await driver.idle()
            # Wait for all monitor queues to drain
            for monitor in monitors:
                self._orch_log.debug(f"Waiting for monitor '{monitor.name}' to go idle")
                await monitor.idle()
            # Wait for processes
            procs, self._processes = self._processes, {}
            for name, proc in procs.items():
                self._orch_log.debug(f"Waiting for process '{name}' to complete")
                await proc
            # Drain the scoreboard
            await self.scoreboard.drain()
        # Run teardown steps
        for teardown in self._teardown:
            await teardown

    @classmethod
    def testcase(
        cls,
        *args,
        reset=True,
        timeout=10000,
        shutdown_loops=2,
        shutdown_delay=100,
        reset_init=True,
        reset_wait_during=20,
        reset_wait_after=1,
        **kwargs,
    ) -> Callable:
        """
        Custom testcase declaration, wraps test with bench class

        :param reset:             Whether to reset the design
        :param timeout:           Maximum run time for a test (in clock cycles)
        :param shutdown_loops:    Number of loops of the shutdown sequence
        :param shutdown_delay:    Delay between loops of the shutdown sequence
        :param reset_init:        Initialise the DUT's I/O
        :param reset_wait_during: Clock cycles to hold reset active for
                                  (defaults to 20)
        :param reset_wait_after:  Clock cycles to wait after lowering reset
                                  (defaults to 1)
        """

        class _Testcase(cocotb.test):
            def __call__(self, dut, *args, **kwargs):
                async def _run_test():
                    # Clear components registered from previous runs
                    Component.COMPONENTS.clear()
                    # Create a testbench instance
                    try:
                        tb = cls(dut)
                    except Exception as e:
                        dut._log.error(f"Caught exception during {cls.__name__} constuction: {e}")
                        dut._log.error(traceback.format_exc())
                        raise e
                    # Log what's going on
                    tc_name = self._func.__name__
                    tb._orch_log.info(f"Preparing testcase {tc_name}")
                    # Check all components have been registered
                    missing = 0
                    for comp in Component.COMPONENTS:
                        if comp not in tb._components.values():
                            tb._orch_log.error(
                                f"{type(comp).__name__} '{comp.name}' has "
                                f"not been registered with the testbench"
                            )
                            missing += 1
                    assert missing == 0, "Some bench components have not been registered"
                    # If clock driving specified, start the clock
                    if tb.clk_drive:
                        cocotb.start_soon(Clock(tb.clk, tb.clk_period, units=tb.clk_units).start())
                    # If reset requested, run the sequence
                    if reset:
                        tb._orch_log.info("Resetting the DUT")
                        try:
                            await tb.reset(
                                init=reset_init,
                                wait_during=reset_wait_during,
                                wait_after=reset_wait_after,
                            )
                        except Exception as e:
                            tb._orch_log.error(f"Caught exception during reset: {e}")
                            tb._orch_log.error(traceback.format_exc())
                            raise e
                        tb._orch_log.info("DUT reset complete")

                    # Mark ready
                    tb.evt_ready.set()

                    # Wait for all components to be ready
                    for comp in tb._components.values():
                        await comp.ready()

                    # Create a forked log
                    log = tb.fork_log("test", tc_name)

                    # Are there any parameters for this test?
                    raw_tc_params = cls.get_parameter("testcases")
                    params = {}
                    for key, cast in cls.TEST_REQ_PARAMS[self._func]:
                        # First look for "<TESTCASE_NAME>.<PARAMETER_NAME>"
                        # but fall back to just "<PARAMETER_NAME>"
                        value = raw_tc_params.get(f"{tc_name}.{key}", raw_tc_params.get(key, None))
                        if value is None:
                            continue

                        # Cast string values to the appropriate type
                        if isinstance(value, str) and cast is not str:
                            if cast is bool:
                                value = strtobool(value)
                            else:
                                value = cast(value)

                        log.debug(f"Parameter {key}={value}")
                        params[key] = value

                    # Declare an intermediate function (this allows us to wrap
                    # with a optional timeout)
                    async def _inner():
                        await self._func(tb, log, *args, **kwargs, **params)
                        await tb.close_down(loops=shutdown_loops, delay=shutdown_delay)

                    # Run with a timeout if specified
                    postponed = None
                    if timeout is None:
                        await _inner()
                    else:
                        try:
                            await with_timeout(_inner(), timeout, "ns")
                        except SimTimeoutError as e:
                            postponed = e
                            tb._orch_log.error(f"Simulation timed out after {timeout} ns")
                            # List any busy drivers
                            for name, driver in tb._components.items():
                                if isinstance(driver, BaseDriver) and driver.queued > 0:
                                    tb._orch_log.info(
                                        f"Driver {name} has {driver.queued} "
                                        f"items remaining in its queue"
                                    )

                    # Report status of scoreboard channels
                    for _, channel in tb.scoreboard.channels.items():
                        channel.report()

                    # When using postmortem, catch errors before exit
                    if tb.get_parameter("postmortem", False) and (
                        (postponed is not None) or not tb.scoreboard.result
                    ):
                        tb._orch_log.warning("Entering postmortem")
                        breakpoint()

                    # If an exception has been postponed, re-raise it now
                    if postponed is not None:
                        raise postponed

                    # Check the result
                    assert tb.scoreboard.result, "Scoreboard reported test failure"

                return cocotb.decorators._RunningTest(_run_test(), self)

        def _do_decorate(func):
            # _testcase acts as a function which returns a decorator, hence the
            # double function call
            return _Testcase(*args, **kwargs)(func)

        return _do_decorate

    @classmethod
    def parameter(cls, name: str, cast: Callable[[str], Any]) -> Callable:
        """
        Decorator for defining a parameter of a testcase that can be overridden
        from a parameter file identified by the `TEST_PARAMS` environment
        variable.

        :param name: Name of the parameter
        :param cast: Function to cast a string param to the required type,
                     usually just the type constructor e.g. `int`, `float`.
                     As a special case `bool` will match intuitively based
                     on string content, e.g. `True, y, False, NO, 1, 0, off`.
        """

        def _inner(method: Callable) -> Callable:
            cls.TEST_REQ_PARAMS[method].append((name, cast))
            return method

        return _inner


# Start profiling when it is enabled in the parameters file
if outfile := BaseBench.get_parameter("profiling"):
    import atexit

    import yappi

    logging.warning("Profiling has been enabled")
    yappi.set_clock_type("wall")
    yappi.start()

    # Register a teardown method to stop profiling when Python exits
    def _end_profile():
        yappi.stop()
        logging.info("Profiling summary:")
        logging.info(yappi.get_func_stats().print_all())
        logging.info(f"Profile data written to {outfile}")
        yappi.get_func_stats().save(outfile, type="pstat")

    atexit.register(_end_profile)
