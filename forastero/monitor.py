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

from collections.abc import Callable
from enum import Enum, auto

import cocotb
from cocotb.triggers import RisingEdge

from .component import Component
from .transaction import BaseTransaction


class MonitorEvent(Enum):
    CAPTURE = auto()


class BaseMonitor(Component):
    """
    Component for sampling transactions from an interface matching the
    implementation's signalling protocol.

    :param tb:      Handle to the testbench
    :param io:      Handle to the BaseIO interface
    :param clk:     Clock signal to use when driving/sampling the interface
    :param rst:     Reset signal to use when driving/sampling the interface
    :param random:  Random number generator to use (optional)
    :param name:    Unique name for this component instance (optional)
    """

    def __init__(self, *args, **kwds) -> None:
        super().__init__(*args, **kwds)
        cocotb.start_soon(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        await self.tb.ready()
        await RisingEdge(self.clk)

        def _capture(obj: BaseTransaction):
            self.publish(MonitorEvent.CAPTURE, obj)

        while True:
            await self.monitor(_capture)

    async def monitor(self, capture: Callable) -> None:
        del capture
        raise NotImplementedError("monitor is not implemented on BaseMonitor")
