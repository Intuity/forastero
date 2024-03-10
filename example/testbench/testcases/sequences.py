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

from random import Random

import forastero
from cocotb.log import SimLog
from forastero.driver import DriverEvent

from ..stream import StreamInitiator, StreamResponder, StreamBackpressure, StreamTransaction
from ..testbench import Testbench

@forastero.sequence()
@forastero.requires("stream", StreamInitiator)
async def random_traffic(log: SimLog,
                         random: Random,
                         stream: StreamInitiator,
                         length: int = 1000):
    """ Generates random traffic """
    log.info(f"Generating {length} random transactions")
    for _ in range(length):
        stream.enqueue(StreamTransaction(data=random.getrandbits(32)))


@forastero.sequence()
@forastero.requires("stream", StreamResponder)
async def random_backpressure(log: SimLog,
                              random: Random,
                              stream: StreamResponder):
    """ Generates infinite random backpressure """
    log.info("Generating infinite random backpressure")
    while True:
        stream.enqueue(StreamBackpressure(ready=random.choice((True, False)),
                                          cycles=random.randint(1, 10)))
        await stream.wait_for(DriverEvent.PRE_DRIVE)


@Testbench.testcase()
async def random_seq(tb: Testbench, log: SimLog) -> None:
    tb.schedule(random_traffic(stream=tb.a_init, length=2000))
    tb.schedule(random_traffic(stream=tb.b_init, length=2000))
    tb.schedule(random_backpressure(stream=tb.x_resp))
