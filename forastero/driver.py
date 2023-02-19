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

from cocotb.triggers import RisingEdge
from cocotb_bus.drivers import Driver

class BaseDriver(Driver):
    """ Base class for drivers """

    def __init__(self, entity, clock, reset, intf, name=None, delay=(0, 0)):
        """ Initialise the BaseDriver instance.

        Args:
            entity     : Pointer to the testbench/DUT
            clock      : Clock signal for the interface
            reset      : Reset signal for the interface
            intf       : Interface
            name       : Optional name of the monitor (defaults to the class)
            delay      : Tuple of min-max delays
            probability: Probability of delay
        """
        self.name   = name or type(self).__name__
        self.entity = entity
        self.clock  = clock
        self.reset  = reset
        self.intf   = intf
        self.delay  = delay
        self.busy   = False
        super().__init__()

    def lock(self) -> None:
        self.busy = True

    def release(self) -> None:
        self.busy = False

    async def idle(self):
        await RisingEdge(self.clock)
        if not self._sendQ and not self.busy: return
        while self._sendQ or self.busy: await RisingEdge(self.clock)
