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

from enum import Enum
import os
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from cocotb_bus.scoreboard import Scoreboard
from cocotb_bus.drivers import Driver

from .driver import BaseDriver
from .io import IORole
from .monitor import BaseMonitor

class BaseBench:

    def __init__(self, dut, clk="i_clk", rst="i_rst"):
        """ Initialise the base testbench.

        Args:
            dut: Pointer to the DUT
        """
        # Hold a pointer to the DUT
        self.dut = dut
        # Promote clock & reset
        self.clk = getattr(dut, clk)
        self.rst = getattr(dut, rst)
        # Expose logging methods
        self.debug   = dut._log.debug
        self.info    = dut._log.info
        self.warning = dut._log.warning
        self.error   = dut._log.error
        # Create a scoreboard
        imm_fail = (os.environ.get("FAIL_IMMEDIATELY", "no").lower() == "yes")
        self.scoreboard = Scoreboard(self, fail_immediately=imm_fail)
        # Track drivers and monitors
        self.drivers  = {}
        self.monitors = {}

    async def initialise(self):
        """ Initialise the DUT's I/O """
        self.rst.value = 1
        for driver in self.drivers.values():
            driver.intf.initialise(IORole.opposite(driver.intf.role))
        for monitor in self.monitors.values():
            monitor.intf.initialise(IORole.opposite(monitor.intf.role))

    async def reset(self, init=True, wait=20):
        """ Reset the DUT.

        Args:
            init: Initialise the DUT's I/O
            wait: Number of clock cycles to wait after init and reset
        """
        # Drive reset high
        self.rst.value = 1
        # Initialise I/O
        if init:
            await self.initialise()
            await ClockCycles(self.clk, wait)
        # Drop reset
        self.rst.value = 0
        # Wait for a bit
        await ClockCycles(self.clk, wait)

    def __getattr__(self, key):
        """ Pass through accesses to signals on the DUT.

        Args:
            key: Name of the attribute
        """
        try:
            return getattr(super(), key)
        except Exception:
            return getattr(self.dut, key)

    def register_driver(self, name : str, inst : Driver) -> None:
        """
        Register a driver with the testbench, will be included in the shutdown
        handling.

        Args:
            name: Name of the driver
            inst: Instance of the driver
        """
        assert isinstance(inst, BaseDriver), "Not a subclass of BaseDriver"
        self.drivers[name] = inst
        setattr(self, name, inst)

    def register_monitor(self, name : str, inst : BaseMonitor) -> None:
        """
        Register a monitor with the testbench, creating an expected transaction
        list and linking it to the scoreboard.

        Args:
            name: Name of the monitor to register
            inst: Instance of the monitor
        """
        assert isinstance(inst, BaseMonitor), "Not a subclass of BaseMonitor"
        self.monitors[name] = inst
        setattr(self, name, inst)
        def _compare_func(got : Any):
            return self.__compare_transactions(inst, got)
        self.scoreboard.add_interface(inst,
                                      inst.expected,
                                      compare_fn=_compare_func)

    def __compare_transactions(self, monitor : BaseMonitor, got : Any) -> None:
        """
        Check that the received transaction of a monitor and the next expected
        transaction in the monitor's queue match one another, and verbosely
        print out the differences when an error occurs.

        Args:
            monitor: Pointer to the monitor which collected the transaction
            got    : Transaction received by the monitor
        """
        # Pop the next expected transaction
        exp     = monitor.expected.pop(0)
        fmt_int = lambda x: (hex(x) if not isinstance(x, Enum) and
                                       isinstance(x, int) and
                                       x > 9 else str(x))
        # Check to see expected transaction matches received data
        # NOTE: Monitor's may provide a 'compare' method to override '!='
        if (
            (monitor.compare is     None and exp != got                   ) or
            (monitor.compare is not None and not monitor.compare(got, exp))
        ):
            self.error(
                f"Unexpected {type(exp).__name__} received by {monitor.name} at "
                f"{get_sim_time('ns')} ns:"
            )
            max_key = max((len(x) for x in vars(exp).keys()))
            entries = []
            for key, exp_val in vars(exp).items():
                got_val = getattr(got, key)
                exp_str = fmt_int(exp_val)
                got_str = fmt_int(got_val)
                entries.append((key, exp_str, got_str))
            max_key = max((len(x[0]) for x in entries))
            max_exp = max((len(x[1]) for x in entries))
            max_got = max((len(x[2]) for x in entries))
            for key, exp, got in entries:
                self.info(
                    f" - [{[' ','!'][exp != got]}] {key:<{max_key}s} - "
                    f"E: {exp:<{max_exp}s}, G: {got:<{max_got}s}"
                )
            self.scoreboard.errors += 1
            if self.scoreboard._imm:
                assert self.scoreboard.errors == 0

    async def close_down(self) -> None:
        """ Wait for all drivers and monitors to drain """
        # Wait for all drivers to return to idle
        for key, driver in self.drivers.items():
            self.info(f"Waiting for driver '{key}' to go idle")
            await driver.idle()
        # Wait for all monitor queues to drain
        for key, monitor in self.monitors.items():
            self.info(f"Waiting for monitor '{key}' to go idle")
            await monitor.idle()

    @classmethod
    def testcase(cls, *args, **kwargs) -> None:
        """ Custom testcase declaration, wraps test with bench class"""
        class _testcase(cocotb.test):
            def __call__(self, dut, *args, **kwargs):
                async def __run_test():
                    tb = cls(dut)
                    await self._func(tb, *args, **kwargs)
                    await tb.close_down()
                    raise tb.scoreboard.result
                return cocotb.decorators.RunningTest(__run_test(), self)
        def _do_decorate(func):
            # _testcase acts as a function which returns a decorator, hence the
            # double function call
            return _testcase(*args, **kwargs)(func)
        return _do_decorate
