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
from typing import Any

from cocotb.triggers import RisingEdge
from cocotb_bus.drivers import Driver

from .io import BaseIO


class BaseDriver(Driver):
    """Base class for drivers"""

    def __init__(
        self,
        entity: Any,
        clock: Any,
        reset: Any,
        intf: BaseIO,
        name: str | None = None,
        delay: tuple[int, int] = (0, 0),
        probability: float = 1.0,
        sniffer: Callable | None = None,
    ):
        """Initialise the BaseDriver instance.

        Args:
            entity     : Pointer to the testbench/DUT
            clock      : Clock signal for the interface
            reset      : Reset signal for the interface
            intf       : Interface
            name       : Optional name of the monitor (defaults to the class)
            delay      : Tuple of min-max delays
            probability: Probability of delay
            sniffer    : Optional function to call each time a queued packet is
                         driven into the design
        """
        self.name = name or type(self).__name__
        self.entity = entity
        self.clock = clock
        self.reset = reset
        self.intf = intf
        self.delay = delay
        self.probability = probability
        self.sniffer = sniffer
        self.busy = False
        super().__init__()

    def lock(self) -> None:
        self.busy = True

    def release(self) -> None:
        self.busy = False

    async def idle(self):
        await RisingEdge(self.clock)
        if not self._sendQ and not self.busy:
            return
        while self._sendQ or self.busy:
            await RisingEdge(self.clock)

    def sniff(self, transaction: Any) -> None:
        """Provide packet to sniffer, if defined"""
        if self.sniffer:
            self.sniffer(driver=self, transaction=transaction)
