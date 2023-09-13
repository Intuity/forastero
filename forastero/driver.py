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

from enum import Enum, auto

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .component import Component
from .transaction import BaseTransaction


class DriverEvent(Enum):
    PRE_DRIVE = auto()
    POST_DRIVE = auto()


class BaseDriver(Component):
    """
    Component for driving transactions onto an interface matching the
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
        self._queue: Queue[BaseTransaction] = Queue()
        cocotb.start_soon(self._driver_loop())

    @property
    def busy(self):
        """Busy when either locked or the queue has outstanding entries"""
        return not self._queue.empty() and super().busy

    def enqueue(self, transaction: BaseTransaction) -> None:
        """
        Queue up a transaction to be driven onto the interface

        :param transaction: Transaction to queue, must inherit from BaseTransaction
        """
        if not isinstance(transaction, BaseTransaction):
            raise TypeError(
                f"Transaction objects should inherit from "
                f"BaseTransaction unlike {transaction}"
            )
        self._queue.put_nowait(transaction)

    async def _driver_loop(self) -> None:
        """Main loop for driving transactions onto the interface"""
        await self.tb.ready()
        await RisingEdge(self.clk)
        self._ready.set()
        while True:
            obj = await self._queue.get()
            while self.rst.value == 1:
                await RisingEdge(self.clk)
            await self.lock()
            obj.timestamp = get_sim_time(units="ns")
            self.publish(DriverEvent.PRE_DRIVE, obj)
            await self.drive(obj)
            self.publish(DriverEvent.POST_DRIVE, obj)
            self.release()

    async def drive(self, obj: BaseTransaction) -> None:
        """
        Placeholder driver, this should be overridden by a child class to match
        the signalling protocol of the interface's implementation.

        :param obj: The transaction to drive onto the interface
        """
        del obj
        raise NotImplementedError("drive is not implemented on BaseDriver")
