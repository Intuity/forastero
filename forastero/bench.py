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

import random
from dataclasses import is_dataclass
from enum import Enum
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.handle import HierarchyObject, ModifiableObject
from cocotb.triggers import ClockCycles, Event, with_timeout
from cocotb.utils import get_sim_time

from .component import Component
from .driver import BaseDriver
from .io import IORole
from .monitor import BaseMonitor


class BaseBench:
    def __init__(
        self,
        dut: HierarchyObject,
        clk: ModifiableObject | None = None,
        rst: ModifiableObject | None = None,
        clk_drive: bool = True,
        clk_period: float = 1,
        clk_units: str = "ns",
    ) -> None:
        """Initialise the base testbench.

        Args:
            dut: Pointer to the DUT
        """
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
        # imm_fail = os.environ.get("FAIL_IMMEDIATELY", "no").lower() == "yes"
        # self.scoreboard = Scoreboard(self, fail_immediately=imm_fail)
        # Track components
        self.components = {}
        # Random seeding
        self.seed = 0
        self.random = random.Random(self.seed)
        # Events
        self.evt_ready = Event()

    async def ready(self) -> None:
        """Blocks until reset has completed"""
        await self.evt_ready.wait()
        self.evt_ready.clear()

    async def initialise(self):
        """Initialise the DUT's I/O"""
        self.rst.value = 1
        for comp in self.components.values():
            comp.io.initialise(IORole.opposite(comp.io.role))

    async def reset(self, init=True, wait_during=20, wait_after=1):
        """Reset the DUT.

        Args:
            init       : Initialise the DUT's I/O
            wait_during: Clock cycles to hold reset active for (defaults to 20)
            wait_after : Clock cycles to wait after lowering reset (defaults to 1)
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

    def __getattr__(self, key):
        """Pass through accesses to signals on the DUT.

        Args:
            key: Name of the attribute
        """
        try:
            return getattr(super(), key)
        except Exception:
            return getattr(self.dut, key)

    def register(self, name: str, inst: Component) -> None:
        """
        Register a driver or a monitor providing they inherit from BaseDriver or
        BaseMonitor types.

        Args:
            name: Name of the driver/monitor
            inst: Instance of the driver/monitor
        """
        if isinstance(inst, Component):
            self.components[name] = inst
            inst.name = name
            setattr(self, name, inst)
            inst.seed(self.random)
        else:
            raise TypeError(f"Unsupported object: {inst}")

    def __compare_transactions(self, monitor: BaseMonitor, got: Any) -> None:
        """
        Check that the received transaction of a monitor and the next expected
        transaction in the monitor's queue match one another, and verbosely
        print out the differences when an error occurs.

        Args:
            monitor: Pointer to the monitor which collected the transaction
            got    : Transaction received by the monitor
        """
        # Pop the next expected transaction
        if len(monitor.expected) == 0:
            self.scoreboard.errors += 1
            self.error(
                f"No expected packets queued on monitor {monitor.name} for: {got}"
            )
            return
        exp = monitor.expected.pop(0)

        def fmt_int(x):
            return (
                hex(x)
                if not isinstance(x, Enum) and isinstance(x, int) and x > 9
                else str(x)
            )

        # Check to see expected transaction matches received data
        # NOTE: Monitor's may provide a 'compare' method to override '!='
        if (monitor.compare is None and exp != got) or (
            monitor.compare is not None and not monitor.compare(got, exp)
        ):
            self.error(
                f"Unexpected {type(exp).__name__} received by {monitor.name} at "
                f"{get_sim_time('ns')} ns:"
            )
            if is_dataclass(exp):
                max_key = max(len(x) for x in vars(exp).keys())
                entries = []
                for key, exp_val in vars(exp).items():
                    got_val = getattr(got, key)
                    exp_str = fmt_int(exp_val)
                    got_str = fmt_int(got_val)
                    entries.append((key, exp_str, got_str))
                max_key = max(len(x[0]) for x in entries)
                max_exp = max(len(x[1]) for x in entries)
                max_got = max(len(x[2]) for x in entries)
                for key, exp, got in entries:
                    self.info(
                        f" - [{[' ','!'][exp != got]}] {key:<{max_key}s} - "
                        f"E: {exp:<{max_exp}s}, G: {got:<{max_got}s}"
                    )
            else:
                self.info(
                    f" - [{[' ','!'][exp != got]}] E: {fmt_int(exp)}, G: {fmt_int(got)}"
                )
            self.scoreboard.errors += 1
            if self.scoreboard._imm:
                assert self.scoreboard.errors == 0

    async def close_down(self, shutdown_loops: int = 2) -> None:
        """Wait for all drivers and monitors to drain"""
        # Filter drivers and monitors into separate lists
        drivers, monitors = [], []
        for comp in self.components.values():
            [monitors, drivers][isinstance(comp, BaseDriver)].append(comp)
        # Check for consistent idleness
        self.info("Shutdown loop starting")
        for shutdown_loop_count in range(1, shutdown_loops + 1):
            await ClockCycles(self.clk, 100)
            # Wait for all drivers to return to idle
            for driver in drivers:
                self.info(f"Waiting for driver '{driver.name}' to go idle")
                await driver.idle()
            # Wait for all monitor queues to drain
            for monitor in monitors:
                self.info(f"Waiting for monitor '{monitor.name}' to go idle")
                await monitor.idle()
            # All drivers and monitors should be idle
            self.info(f"Shutdown loop count ({shutdown_loop_count}/{shutdown_loops})")

    @classmethod
    def testcase(
        cls, *args, reset=True, timeout=None, shutdown_loops=2, **kwargs
    ) -> None:
        """Custom testcase declaration, wraps test with bench class"""

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

                    async def _inner():
                        await self._func(tb, *args, **kwargs)
                        await tb.close_down(shutdown_loops=shutdown_loops)

                    if timeout is None:
                        await _inner()
                    else:
                        await with_timeout(_inner(), timeout, "ns")
                    # raise tb.scoreboard.result

                return cocotb.decorators._RunningTest(_run_test(), self)

        def _do_decorate(func):
            # _testcase acts as a function which returns a decorator, hence the
            # double function call
            return _Testcase(*args, **kwargs)(func)

        return _do_decorate
