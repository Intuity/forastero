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

import cocotb
from cocotb.log import _COCOTB_LOG_LEVEL_DEFAULT, SimLog
from cocotb.queue import Queue
from cocotb.triggers import RisingEdge

from .monitor import BaseMonitor, MonitorEvent
from .transaction import BaseTransaction


class Channel:
    """
    A channel gathers transactions from a monitor and a reference model of some
    form. When both queues contain an entry, the top-most entry is popped from
    both queues and tested for equivalence. Any mismatches are reported to the
    scoreboard.

    :param monitor: Handle to the monitor capturing traffic from the DUT
    :param log:     Handle to the scoreboard log
    """

    def __init__(self, monitor: BaseMonitor, log: SimLog) -> None:
        self.monitor = monitor
        self.log = log
        self._q_mon = Queue()
        self._q_ref = Queue()

        def _sample(mon: BaseMonitor, evt: MonitorEvent, obj: BaseTransaction) -> None:
            if mon is self.monitor and evt is MonitorEvent.CAPTURE:
                self.push_monitor(obj)

        self.monitor.subscribe(MonitorEvent.CAPTURE, _sample)

    def push_monitor(self, *transactions: BaseTransaction) -> None:
        """
        Push one or more captured transactions into the monitor's queue.

        :param *transactions: Captured transactions
        """
        for transaction in transactions:
            assert isinstance(transaction, BaseTransaction)
            self._q_mon.put_nowait(transaction)

    def push_reference(self, *transactions: BaseException) -> None:
        """
        Push one or more captured transactions into the reference (model) queue.

        :param *transactions: Captured transactions
        """
        for transaction in transactions:
            assert isinstance(transaction, BaseTransaction)
            self._q_ref.put_nowait(transaction)

    async def dequeue(self) -> tuple[BaseTransaction, BaseTransaction]:
        """
        Dequeue the top-most transaction from both the monitor and reference
        queues.

        :returns: Tuple of the monitor transaction and reference transaction
        """
        next_mon = await self._q_mon.get()
        next_ref = await self._q_ref.get()
        return next_mon, next_ref

    async def loop(self, mismatch: Callable) -> None:
        """
        Continuously dequeue pairs of transactions from the monitor and reference
        queues and report mismatches to the scoreboard via the callback.

        :param mismatch: Callback to execute whenever a mismatch occurs, providing
                         arguments of the channel (self), the monitor object, and
                         the reference object
        """
        while True:
            mon, ref = await self.dequeue()
            if mon != ref:
                mismatch(self, mon, ref)

    async def drain(self) -> None:
        """Block until the channel's monitor and reference queues empty"""
        while not self._q_mon.empty() or not self._q_ref.empty():
            await RisingEdge(self.monitor.clk)


class Scoreboard:
    """
    Scoreboard for comparing captured and reference transactions. The scoreboard
    is divided into different 'channels', one per monitor, that handle the
    comparison of captured and reference objects and reporting of any differences.

    :param fail_fast: Stop the test as soon as a mismatch is reported (default: False)
    """

    def __init__(self, fail_fast: bool = False):
        self.fail_fast = fail_fast
        self._mismatches = []
        self.log = SimLog(name="Scoreboard")
        self.log.setLevel(_COCOTB_LOG_LEVEL_DEFAULT)
        self.channels: dict[str, Channel] = {}

    def attach(self, monitor: BaseMonitor) -> None:
        """
        Attach a monitor to the scoreboard, creating and scheduling a new
        channel in the process.

        :param monitor: The monitor to attach
        """
        assert monitor.name not in self.channels, f"Monitor known for '{monitor.name}'"
        self.channels[monitor.name] = (chan := Channel(monitor, self.log))
        cocotb.start_soon(chan.loop(self._mismatch))

    async def drain(self) -> None:
        """Block until all chains of the scoreboard have been drained"""
        for name, channel in self.channels.items():
            self.log.info(f"Draining scoreboard channel '{name}'...")
            await channel.drain()
            self.log.info(f"Drained scoreboard channel '{name}'")

    def _mismatch(
        self, channel: Channel, monitor: BaseTransaction, reference: BaseTransaction
    ) -> None:
        """
        Callback whenever a channel detects a mismatch between captured and
        reference objects. If fail_fast is enabled, then an assertion will fire.

        :param channel:   The channel reporting the mismatch
        :param monitor:   The transaction captured by a monitor
        :param reference: The reference transaction produced by a model
        """
        self.log.error(f"{channel.monitor.name} recorded miscomparison")
        self.log.info(monitor.tabulate(reference))
        self._mismatches.append((channel, monitor, reference))
        if self.fail_fast:
            assert "Miscomparison caused fast failure"

    @property
    def result(self) -> bool:
        """If no mismatches recorded return True, else return False"""
        return len(self._mismatches) == 0
