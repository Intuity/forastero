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

import dataclasses
from collections.abc import Iterable
from enum import Enum, auto
from random import Random
from typing import Any

import cocotb
from cocotb.handle import SimHandleBase
from cocotb.triggers import Event, RisingEdge
from cocotb.utils import get_sim_time

from .component import Component
from .io import BaseIO
from .queue import Queue
from .transaction import BaseTransaction


class DriverEvent(Enum):
    ENQUEUE = auto()
    """Emitted when a transaction is enqueued to a driver"""
    PRE_DRIVE = auto()
    """Emitted just prior to a queued transaction being driven into the DUT"""
    POST_DRIVE = auto()
    """Emitted just after a queued transaction has been driven into the DUT"""


@dataclasses.dataclass()
class DriverStatistics:
    dequeued: int = 0


@dataclasses.dataclass()
class EnqueuedIterable:
    iterable: Iterable
    wait_for: DriverEvent


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

    def __init__(
        self,
        tb: Any,
        io: BaseIO,
        clk: SimHandleBase,
        rst: SimHandleBase,
        random: Random | None = None,
        name: str | None = None,
        blocking: bool = True,
    ) -> None:
        super().__init__(tb, io, clk, rst, random, name, blocking)
        self.stats = DriverStatistics()
        self._queue: Queue[BaseTransaction] = Queue()
        cocotb.start_soon(self._driver_loop())

    @property
    def busy(self) -> bool:
        """Busy when either locked or the queue has outstanding entries"""
        return (self._queue.level > 0) and super().busy

    @property
    def queued(self) -> int:
        """Return how many entries are queued up"""
        return self._queue.level

    def enqueue(
        self,
        transaction: BaseTransaction | Iterable[BaseTransaction],
        wait_for: DriverEvent | None = None,
    ) -> Event | None:
        """
        Queue up a transaction to be driven onto the interface

        :param transaction: Transaction to queue, must inherit from BaseTransaction,
                            or be an iterable which yields BaseTransaction
        :param wait_for:    When defined, this will return an event that can be
                            monitored for a given transaction event occurring
        """
        # Sanity check
        if not isinstance(transaction, BaseTransaction | Iterable):
            raise TypeError(
                f"Transaction objects should inherit from BaseTransaction unlike {transaction}"
            )
        if isinstance(transaction, BaseTransaction):
            # Does this transaction need an event?
            if wait_for is not None:
                transaction._f_event = wait_for
                transaction._c_event = Event()
            # Queue up the transaction with no delay
            self._queue.push(transaction)
            # Notify any enqueue subscribers
            self.publish(DriverEvent.ENQUEUE, transaction)
            if transaction._f_event is DriverEvent.ENQUEUE:
                transaction._c_event.set()
            # Return the cocotb Event (if it was set)
            return transaction._c_event
        else:
            # Add wait_for and iterable to a namedTuple
            transaction = EnqueuedIterable(iterable=transaction, wait_for=wait_for)
            # Queue up the transaction with no delay
            self._queue.push(transaction)
            self.publish(DriverEvent.ENQUEUE, transaction)
            _c_event = None
            if wait_for and wait_for._f_event is DriverEvent.ENQUEUE:
                _c_event = Event()
                _c_event.set()
            # Return the cocotb Event (if it was set)
            return _c_event

    async def get_from_queue(self) -> BaseTransaction:
        """
        Fetch next item from the queue.
        Process iterables and add events to yielded BaseTransaction
        """
        while True:
            await self._queue.wait_for_not_empty()
            obj = self._queue.peek()
            if isinstance(obj, BaseTransaction):
                obj = await self._queue.pop()
                return obj
            else:
                # obj is an EnqueuedIterable - yield from iterable, append events (if any)
                # and pop from queue when exhausted
                while True:
                    try:
                        if not hasattr(obj, "_iterator"):
                            obj._iterator = iter(obj.iterable)
                        next_item = next(obj._iterator)
                        # If wait_for is set, attach to the transaction
                        if obj.wait_for is not None and isinstance(next_item, BaseTransaction):
                            next_item._f_event = obj.wait_for
                            next_item._c_event = Event()
                        return next_item
                    except StopIteration:
                        # Remove the exhausted EnqueuedIterable from the queue
                        await self._queue.pop()
                        # After popping, break to outer loop to process the new front item
                        break

    async def _driver_loop(self) -> None:
        """Main loop for driving transactions onto the interface"""
        await self.tb.ready()
        await RisingEdge(self.clk)
        self._ready.set()
        while True:
            # Pickup next event to drive
            obj = await self.get_from_queue()
            # Wait until reset is deasserted
            while self.rst.value == self.tb.rst_active_value:
                await RisingEdge(self.clk)
            # Lock out the driver (prevents shutdown mid-stimulus)
            await self.lock()
            # Set the timestamp where the transaction was about to be driven
            obj.timestamp = get_sim_time(units="ns")
            # Notify any pre-drive subscribers
            self.publish(DriverEvent.PRE_DRIVE, obj)
            if obj._f_event is DriverEvent.PRE_DRIVE:
                obj._c_event.set()
            # Drive the transaction
            await self.drive(obj)
            self.stats.dequeued += 1
            # Notify any post-drive subscribers
            self.publish(DriverEvent.POST_DRIVE, obj)
            if obj._f_event is DriverEvent.POST_DRIVE:
                obj._c_event.set()
            # Release the lock
            self.release()

    async def drive(self, obj: BaseTransaction) -> None:
        """
        Placeholder driver, this should be overridden by a child class to match
        the signalling protocol of the interface's implementation.

        :param obj: The transaction to drive onto the interface
        """
        del obj
        raise NotImplementedError("drive is not implemented on BaseDriver")
