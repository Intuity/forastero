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

from cocotb.log import SimLog
from cocotb.triggers import ClockCycles
from common.io.stream import StreamBackpressure, StreamTransaction

from forastero import DriverEvent

from ..testbench import Testbench


@Testbench.testcase()
@Testbench.parameter("packets")
@Testbench.parameter("delay")
async def random(tb: Testbench, log: SimLog, packets: int = 1000, delay: int = 5000):
    # Disable backpressure on input
    tb.x_resp.enqueue(StreamBackpressure(ready=True))

    # Queue traffic onto interfaces A & B and interleave on the exit port
    for _ in range(packets):
        tb.a_init.enqueue(StreamTransaction(data=tb.random.getrandbits(32)))
        tb.b_init.enqueue(StreamTransaction(data=tb.random.getrandbits(32)))

    # Queue up random backpressure
    def _rand_bp(*_):
        tb.x_resp.enqueue(
            StreamBackpressure(
                ready=tb.random.choice((True, False)), cycles=tb.random.randint(1, 10)
            )
        )

    tb.x_resp.subscribe(DriverEvent.POST_DRIVE, _rand_bp)
    _rand_bp()

    # Register a long-running coroutine
    async def _wait():
        await ClockCycles(tb.clk, delay)

    tb.register("wait", _wait())
