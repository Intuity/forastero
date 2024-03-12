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
from random import Random
from typing import Any, ClassVar

from cocotb.handle import ModifiableObject
from cocotb.triggers import RisingEdge

from .event import EventEmitter
from .io import BaseIO


class Component(EventEmitter):
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

    # Tracks all component instances
    COMPONENTS: ClassVar[list["Component"]] = []

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
        # Setup emitter behaviours
        super().__init__()
        # Setup component variables
        self.tb = tb
        self.io = io
        self.clk = clk
        self.rst = rst
        self.random = Random(random.random() if random else 0)
        self.name = name or type(self).__name__
        self.blocking = blocking
        self.log = self.tb.fork_log(type(self).__name__.lower(), self.name)
        self._lock = asyncio.Lock()
        Component.COMPONENTS.append(self)

    async def ready(self) -> None:
        await self._ready.wait()

    def seed(self, random: Random) -> None:
        """
        Set up the random seed (used by testbench when registering a component)

        :param random:  The random instance to seed from
        """
        self.random = Random(random.random())

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
