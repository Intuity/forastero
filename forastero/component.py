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
from collections import defaultdict
from collections.abc import Callable
from enum import Enum
from random import Random
from typing import Any

from cocotb.handle import ModifiableObject
from cocotb.log import _COCOTB_LOG_LEVEL_DEFAULT, SimLog
from cocotb.triggers import RisingEdge

from .io import BaseIO


class Component:
    """
    Base component type for working with BaseIO interfaces, can be extended to
    form drivers, monitors, and other signalling protocol aware components.

    :param tb:       Handle to the testbench
    :param io:       Handle to the BaseIO interface
    :param clk:      Clock signal to use when driving/sampling the interface
    :param rst:      Reset signal to use when driving/sampling the interface
    :param random:   Random number generator to use (optional)
    :param name:     Unique name for this component instance (optional)
    :param blocking: Whether this component should block shutdown (default: True)
    """

    def __init__(
        self,
        tb: Any,
        io: BaseIO,
        clk: ModifiableObject,
        rst: ModifiableObject,
        random: Random | None = None,
        name: str | None = None,
        blocking: bool = True,
    ) -> None:
        # To avoid an import loop
        from .bench import BaseBench

        assert isinstance(tb, BaseBench), "'tb' should inherit from BaseBench"
        assert isinstance(io, BaseIO), "'io' should inherit from BaseIO"
        self.tb = tb
        self.io = io
        self.clk = clk
        self.rst = rst
        self.random = Random(random.random() if random else 0)
        self.name = name or type(self).__name__
        self.blocking = blocking
        self.log = SimLog(name=self.name)
        self.log.setLevel(_COCOTB_LOG_LEVEL_DEFAULT)
        self._lock = asyncio.Lock()
        self._handlers = defaultdict(list)

    def seed(self, random: Random) -> None:
        """
        Set up the random seed (used by testbench when registering a component)

        :param random:  The random instance to seed from
        """
        self.random = Random(random.random())

    def subscribe(self, event: Enum, callback: Callable) -> None:
        """
        Subscribe to an event being published by this component.

        :param event:    Enumerated event
        :param callback: Method to call when the event occurs, this must accept
                         arguments of component, event type, and an associated
                         object
        """
        if not isinstance(event, Enum):
            raise TypeError(f"Event should inherit from Enum, unlike {event}")
        self._handlers[event].append(callback)

    def publish(self, event: Enum, obj: Any) -> None:
        """
        Publish an event and deliver it to any registered subscribers.

        :param event: Enumerated event
        :param obj:   Object associated to the event
        """
        for handler in self._handlers[event]:
            handler(self, event, obj)

    async def lock(self) -> None:
        """Lock the component's internal lock"""
        await self._lock.acquire()

    def release(self) -> None:
        """Release the component's internal lock"""
        self._lock.release()

    @property
    def busy(self) -> bool:
        """Determine if the component is currently busy"""
        return self._lock.locked()

    async def idle(self) -> None:
        """Blocks until the component is no longer busy"""
        while True:
            await RisingEdge(self.clk)
            if not self.busy:
                break
