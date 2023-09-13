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
import json
import os
import random
from collections import defaultdict
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, ClassVar

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject, ModifiableObject
from cocotb.triggers import ClockCycles, Event, with_timeout

from .component import Component
from .driver import BaseDriver
from .io import IORole
from .monitor import BaseMonitor
from .scoreboard import Scoreboard


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

    TEST_REQ_PARAMS: ClassVar[dict[str, set[str]]] = defaultdict(set)
    PARAM_FILE_PATH: ClassVar[str] = os.environ.get("TEST_PARAMS", None)
    PARSED_PARAMS: ClassVar[dict[str, Any]] = (
        json.loads(Path(PARAM_FILE_PATH).read_text(encoding="utf-8"))
        if PARAM_FILE_PATH
        else {}
    )

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
        # Expose logging methods
        self.debug = dut._log.debug
        self.info = dut._log.info
        self.warning = dut._log.warning
        self.error = dut._log.error
        # # Create a scoreboard
        fail_fast = os.environ.get("FAIL_FAST", "no").lower() == "yes"
        self.scoreboard = Scoreboard(fail_fast=fail_fast)
        # Track components
        self.components = {}
        self.processes = {}
        # Random seeding
        self.seed = int(self.PARSED_PARAMS.get("seed", 0))
        self.info(f"Bench initialised with random seed {self.seed}")
        self.random = random.Random(self.seed)
        # Events
        self.evt_ready = Event()

    async def ready(self) -> None:
        """Blocks until reset has completed"""
        await self.evt_ready.wait()
        self.evt_ready.clear()

    async def initialise(self) -> None:
        """Initialise the DUT's I/O"""
        self.rst.value = 1
        for comp in self.components.values():
            comp.io.initialise(IORole.opposite(comp.io.role))

    async def reset(self, init=True, wait_during=20, wait_after=1) -> None:
        """Reset the DUT.

        :param init       : Initialise the DUT's I/O
        :param wait_during: Clock cycles to hold reset active for (defaults to 20)
        :param wait_after : Clock cycles to wait after lowering reset (defaults to 1)
        """
        # Drive reset high
        self.rst.value = 1
        # Initialise I/O
        if init:
            await self.initialise()
            await ClockCycles(self.clk, wait_during)
        # Drop reset
        self.rst.value = 0
        # Wait for a bit
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
    ) -> None:
        """
        Register a driver, monitor, or coroutine with the testbench. Drivers and
        monitors must be provided a name and their random seeding will be setup
        from the testbench's random instance. Monitors will be registered with
        the scoreboard unless explicitly requested. Coroutines must also be named
        and are required to complete before the test will shutdown.

        :param name:         Name of the component or coroutine
        :param comp_or_coro: Component instance or coroutine
        :param scoreboard:   Only applies to monitors, controls whether it is
                             registered with the scoreboard
        """
        assert isinstance(name, str), f"Name must be a string '{name}'"
        if asyncio.iscoroutine(comp_or_coro):
            assert name not in self.processes, f"Process known for '{name}'"
            task = cocotb.start_soon(comp_or_coro)
            self.processes[name] = task
        elif isinstance(comp_or_coro, Component):
            assert name not in self.components, f"Component known for '{name}'"
            self.components[name] = comp_or_coro
            comp_or_coro.name = name
            setattr(self, name, comp_or_coro)
            comp_or_coro.seed(self.random)
            if scoreboard and isinstance(comp_or_coro, BaseMonitor):
                self.scoreboard.attach(comp_or_coro)
        else:
            raise TypeError(f"Unsupported object: {comp_or_coro}")

    async def close_down(self, loops: int = 2, delay: int = 100) -> None:
        """
        Wait for drivers, monitors, and the scoreboard to drain to ensure that
        the test has completed.

        :param loops: Number of repetitions of the shutdown sequence to run
        :param delay: Number of clock cycles to wait between shutdown loops
        """
        # Filter drivers and monitors into separate lists
        drivers, monitors = [], []
        for comp in self.components.values():
            if not comp.blocking:
                continue
            [monitors, drivers][isinstance(comp, BaseDriver)].append(comp)
        # Check for consistent idleness
        for loop_idx in range(loops):
            # All drivers and monitors should be idle
            self.info(f"Shutdown loop ({loop_idx+1}/{loops})")
            # Wait for
            await ClockCycles(self.clk, delay)
            # Wait for all drivers to return to idle
            for driver in drivers:
                self.info(f"Waiting for driver '{driver.name}' to go idle")
                await driver.idle()
            # Wait for all monitor queues to drain
            for monitor in monitors:
                self.info(f"Waiting for monitor '{monitor.name}' to go idle")
                await monitor.idle()
            # Wait for processes
            procs, self.processes = self.processes, {}
            for name, proc in procs.items():
                self.info(f"Waiting for process '{name}' to complete")
                await proc
            # Drain the scoreboard
            await self.scoreboard.drain()

    @classmethod
    def testcase(
        cls,
        *args,
        reset=True,
        timeout=10000,
        shutdown_loops=2,
        shutdown_delay=100,
        **kwargs,
    ) -> Callable:
        """
        Custom testcase declaration, wraps test with bench class

        :param reset:          Whether to reset the design
        :param timeout:        Maximum run time for a test (in clock cycles)
        :param shutdown_loops: Number of loops of the shutdown sequence
        :param shutdown_delay: Delay between loops of the shutdown sequence
        """

        class _Testcase(cocotb.test):
            def __call__(self, dut, *args, **kwargs):
                async def _run_test():
                    tb = cls(dut)
                    if tb.clk_drive:
                        cocotb.start_soon(
                            Clock(tb.clk, tb.clk_period, units=tb.clk_units).start()
                        )
                    if reset:
                        tb.info("Resetting the DUT")
                        await tb.reset()
                        tb.info("DUT reset complete")

                    # Mark ready
                    tb.evt_ready.set()

                    # Are there any parameters for this test?
                    params = {
                        x: cls.PARSED_PARAMS[x]
                        for x in cls.TEST_REQ_PARAMS[self._func]
                        if x in cls.PARSED_PARAMS
                    }

                    async def _inner():
                        await self._func(tb, *args, **kwargs, **params)
                        await tb.close_down(loops=shutdown_loops, delay=shutdown_delay)

                    # Run with a timeout if specified
                    if timeout is None:
                        await _inner()
                    else:
                        await with_timeout(_inner(), timeout, "ns")

                    # Check the result
                    assert tb.scoreboard.result, "Scoreboard reported test failure"

                return cocotb.decorators._RunningTest(_run_test(), self)

        def _do_decorate(func):
            # _testcase acts as a function which returns a decorator, hence the
            # double function call
            return _Testcase(*args, **kwargs)(func)

        return _do_decorate

    @classmethod
    def parameter(cls, name: str) -> Callable:
        """
        Decorator for defining a parameter of a testcase that can be overridden
        from a parameter file identified by the `TEST_PARAMS` environment
        variable.

        :param name: Name of the parameter
        """

        def _inner(method: Callable) -> Callable:
            cls.TEST_REQ_PARAMS[method].add(name)
            return method

        return _inner
