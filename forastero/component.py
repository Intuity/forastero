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
        clk: ModifiableObject,
        rst: ModifiableObject,
        random: Random | None = None,
        name: str | None = None,
    ) -> None:
        # To avoid an import loop
        from .bench import BaseBench

        assert isinstance(tb, BaseBench), "'tb' should inherit from BaseBench"
        assert isinstance(io, BaseIO), "'io' should inherit from BaseIO"
        self.tb = tb
        self.io = io
        self.clk = clk
        self.rst = rst
        self.name = name or type(self).__name__
        self.random = Random(random.random() if random else 0)
        self.log = SimLog(name=self.name)
        self.log.setLevel(_COCOTB_LOG_LEVEL_DEFAULT)
        self._lock = asyncio.Lock()
        self._handlers = defaultdict(list)

    def seed(self, random: Random) -> None:
        self.random = Random(random.random())

    def subscribe(self, event: Enum, callback: Callable) -> None:
        if not isinstance(event, Enum):
            raise TypeError(f"Event should inherit from Enum, unlike {event}")
        self._handlers[event].append(callback)

    def publish(self, event: Enum, obj: Any) -> None:
        for handler in self._handlers[event]:
            handler(self, event, obj)

    async def lock(self) -> None:
        await self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def idle(self) -> None:
        while True:
            await RisingEdge(self.clk)
            if not self.busy:
                break
