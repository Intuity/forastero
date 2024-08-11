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
from forastero import DriverEvent, SeqContext

from .initiator import StreamInitiator
from .responder import StreamResponder
from .transaction import StreamBackpressure, StreamTransaction


@forastero.sequence()
@forastero.requires("stream", StreamInitiator)
@forastero.randarg("length", range=(100, 1000))
async def stream_traffic_seq(ctx: SeqContext, stream: StreamInitiator, length: int):
    """
    Generates random traffic on a stream interface, locking and releasing the
    driver for each packet.

    :param length: Length of the stream of traffic to produce
    """
    ctx.log.info(f"Generating {length} random transactions")
    for _ in range(length):
        async with ctx.lock(stream):
            stream.enqueue(StreamTransaction(data=ctx.random.getrandbits(32)))


@forastero.sequence()
@forastero.requires("stream", StreamResponder)
@forastero.randarg("min_interval", range=(1, 10))
@forastero.randarg("max_interval", range=(10, 20))
@forastero.randarg("backpressure", range=(0.1, 0.9))
async def stream_backpressure_seq(
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
