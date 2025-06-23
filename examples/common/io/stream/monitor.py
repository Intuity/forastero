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

from cocotb.triggers import RisingEdge

from forastero import BaseMonitor

from .transaction import StreamTransaction


class StreamMonitor(BaseMonitor):
    async def monitor(self, capture: Callable) -> None:
        while True:
            await RisingEdge(self.clk)
            if self.rst.value == int(self.tb.reset_active_high):
                continue
            if self.io.get("valid", 1) and self.io.get("ready", 1):
                capture(StreamTransaction(data=self.io.get("data", 0)))
