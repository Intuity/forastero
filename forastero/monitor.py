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
from cocotb_bus.monitors import Monitor

from .io import BaseIO


class BaseMonitor(Monitor):
    """Base class for monitors"""

    def __init__(
        self,
        entity: Any,
        clock: Any,
        reset: Any,
        intf: BaseIO,
        name: str | None = None,
        compare: Callable | None = None,
        block: bool = True,
        sniffer: Callable | None = None,
        random: Any | None = None,
    ) -> None:
        """Initialise the BaseMonitor instance.

        Args:
            entity : Pointer to the testbench/DUT
            clock  : Clock signal for the interface
            reset  : Reset signal for the interface
            intf   : Interface
            name   : Optional name of the monitor (defaults to the class)
            compare: Function to compare transactions
            block  : Whether or not to block closedown of the simulation
            sniffer: Optional function to call each time a transaction is captured
                     from the design (before submitting to scoreboard)
            random     : Instance of Python's random library
        """
        self.name = name or type(self).__name__
        self.entity = entity
        self.clock = clock
        self.reset = reset
        self.intf = intf
        self.compare = compare
        self.block = block
        self.sniffer = sniffer
        self.expected = []
        self.random = random
        self.valid_data_count = 0
        super().__init__()

    async def idle(self):
        num_expected = None
        while self.expected:
            if num_expected is None or len(self.expected) < (0.5 * num_expected):
                num_expected = len(self.expected)
                self.entity._log.info(
                    f"Monitor '{self.name}' has {num_expected} transactions left"
                )
            await RisingEdge(self.clock)

    def sniff(self, transaction) -> None:
        """Provide packet to sniffer, if defined"""
        if self.sniffer:
            self.sniffer(component=self, transaction=transaction)
        self.valid_data_count += 1
