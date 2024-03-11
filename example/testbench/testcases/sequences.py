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


import forastero
from cocotb.log import SimLog
from forastero.driver import DriverEvent
from forastero.sequence import SeqContext

from ..stream import StreamInitiator, StreamResponder, StreamBackpressure, StreamTransaction
from ..testbench import Testbench

@forastero.sequence()
@forastero.requires("stream", StreamInitiator)
async def random_traffic(ctx: SeqContext,
                         stream: StreamInitiator,
                         length: int = 1000):
    """ Generates random traffic """
    ctx.log.info(f"Generating {length} random transactions")
    for _ in range(length):
        async with ctx.lock(stream):
            stream.enqueue(StreamTransaction(data=ctx.random.getrandbits(32)))


@forastero.sequence()
@forastero.requires("stream_a", StreamInitiator)
@forastero.requires("stream_b", StreamInitiator)
async def burst_on_a_only(ctx: SeqContext,
                          stream_a: StreamInitiator,
                          stream_b: StreamInitiator,
                          length: int = 64):
    """ Generates a burst only on one channel """
    async with ctx.lock(stream_a, stream_b):
        await stream_a.idle()
        await stream_b.idle()
        ctx.log.info(f"Driving burst of {length} packets on stream A")
        for _ in range(length):
            stream_a.enqueue(StreamTransaction(data=ctx.random.getrandbits(32)))
        await stream_a.idle()


@forastero.sequence()
@forastero.requires("stream", StreamResponder)
async def random_backpressure(ctx: SeqContext,
                              stream: StreamResponder):
    """ Generates infinite random backpressure """
    ctx.log.info("Generating infinite random backpressure")
    async with ctx.lock(stream):
        while True:
            stream.enqueue(StreamBackpressure(ready=ctx.random.choice((True, False)),
                                              cycles=ctx.random.randint(1, 10)))
            await stream.wait_for(DriverEvent.PRE_DRIVE)


@Testbench.testcase(timeout=25000)
async def random_seq(tb: Testbench, log: SimLog) -> None:
    tb.schedule(random_traffic(stream=tb.a_init, length=2000))
    tb.schedule(random_traffic(stream=tb.b_init, length=2000))
    for _ in range(10):
        tb.schedule(burst_on_a_only(stream_a=tb.a_init,
                                    stream_b=tb.b_init,
                                    length=250))
        tb.schedule(burst_on_a_only(stream_a=tb.b_init,
                                    stream_b=tb.a_init,
                                    length=250))
    tb.schedule(random_backpressure(stream=tb.x_resp), blocking=False)
