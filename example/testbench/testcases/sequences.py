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

import forastero
from forastero.driver import DriverEvent
from forastero.sequence import SeqContext

from ..stream import (
    StreamBackpressure,
    StreamInitiator,
    StreamResponder,
    StreamTransaction,
)
from ..testbench import Testbench


@forastero.sequence()
@forastero.requires("stream", StreamInitiator)
@forastero.randarg("length", range=(100, 1000))
async def random_traffic(ctx: SeqContext, stream: StreamInitiator, length: int):
    """Generates random traffic"""
    ctx.log.info(f"Generating {length} random transactions")
    for _ in range(length):
        async with ctx.lock(stream):
            stream.enqueue(StreamTransaction(data=ctx.random.getrandbits(32)))


@forastero.sequence(auto_lock=True)
@forastero.requires("stream_a", StreamInitiator)
@forastero.requires("stream_b", StreamInitiator)
@forastero.randarg("length", range=(1000, 3000))
async def burst_on_a_only(
    ctx: SeqContext,
    stream_a: StreamInitiator,
    stream_b: StreamInitiator,
    length: int,
):
    """Generates a burst only on one channel"""
    await stream_a.idle()
    await stream_b.idle()
    ctx.log.info(f"Driving burst of {length} packets on stream A")
    for _ in range(length):
        stream_a.enqueue(StreamTransaction(data=ctx.random.getrandbits(32)))
    await stream_a.idle()


@forastero.sequence()
@forastero.requires("stream", StreamResponder)
@forastero.randarg("min_interval", range=(1, 10))
@forastero.randarg("max_interval", range=(10, 20))
@forastero.randarg("backpressure", range=(0, 0.9))
async def random_backpressure(
    ctx: SeqContext,
    stream: StreamResponder,
    min_interval: int,
    max_interval: int,
    backpressure: float,
):
    """
    Generate random backpressure using the READY signal of a stream interface,
    with options to tune how often backpressure is applied.

    :param min_interval: Shortest time to hold ready constant
    :param max_interval: Longest time to hold ready constant
    :param backpressure: Weighting proportion for how often ready should be low,
                         i.e. values approaching 1 mean always backpressure,
                         while values approaching 0 mean never backpressure
    """
    ctx.log.info("Generating random stream backpressure")
    async with ctx.lock(stream):
        while True:
            await stream.enqueue(
                StreamBackpressure(
                    ready=ctx.random.choices(
                        (True, False),
                        weights=(1.0 - backpressure, backpressure),
                        k=1,
                    )[0],
                    cycles=ctx.random.randint(min_interval, max_interval),
                ),
                DriverEvent.PRE_DRIVE,
            ).wait()


@Testbench.testcase(timeout=100000)
async def random_seq(tb: Testbench, log: SimLog) -> None:
    tb.schedule(random_traffic(stream=tb.a_init, length=2000))
    tb.schedule(random_traffic(stream=tb.b_init, length=2000))
    for _ in range(10):
        tb.schedule(
            burst_on_a_only(
                stream_a=tb.a_init, stream_b=tb.b_init, length_range=(100, 500)
            )
        )
        tb.schedule(
            burst_on_a_only(
                stream_a=tb.b_init, stream_b=tb.a_init, length_range=(100, 500)
            )
        )
    tb.schedule(random_backpressure(stream=tb.x_resp), blocking=False)
