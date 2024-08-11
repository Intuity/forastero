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
from common.io.stream import (
    StreamInitiator,
    StreamTransaction,
    stream_backpressure_seq,
    stream_traffic_seq,
)

import forastero
from forastero.sequence import SeqContext

from ..testbench import Testbench


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
    """
    Generates a burst only on one channel while locking the other channel to
    ensure it is idle.

    :param length: How long the burst of packets should be
    """
    await stream_a.idle()
    await stream_b.idle()
    ctx.log.info(f"Driving burst of {length} packets on stream A")
    for _ in range(length):
        stream_a.enqueue(StreamTransaction(data=ctx.random.getrandbits(32)))
    await stream_a.idle()


@Testbench.testcase(timeout=100000)
@Testbench.parameter("single_pkts")
@Testbench.parameter("burst_count")
@Testbench.parameter("burst_min")
@Testbench.parameter("burst_max")
async def random_seq(
    tb: Testbench,
    log: SimLog,
    single_pkts: int = 2000,
    burst_count: int = 10,
    burst_min: int = 100,
    burst_max: int = 500,
) -> None:
    """
    Stimulate the DUT with random traffic generated through Forastero sequences,
    which are automatically schedule by the testbench.

    :param single_pkts: Number of single packets to drive on interfaces A & B
    :param burst_count: Number of bursts to send on interfaces A & B
    :param burst_min:   Minimum length of each burst
    :param burst_max:   Maximum length of each burst
    """
    # Schedule single packets on upstream interfaces A & B independently
    log.info(f"Scheduling {single_pkts} single packets on A & B")
    tb.schedule(stream_traffic_seq(stream=tb.a_init, length=single_pkts))
    tb.schedule(stream_traffic_seq(stream=tb.b_init, length=single_pkts))
    # Schedule isolated bursts of packets on upstream interfaces A & B
    log.info(
        f"Scheduling {burst_count} bursts between {burst_min} and {burst_max} "
        f"packets in length"
    )
    for _ in range(burst_count):
        tb.schedule(
            burst_on_a_only(
                stream_a=tb.a_init,
                stream_b=tb.b_init,
                length_range=(burst_min, burst_max),
            )
        )
        tb.schedule(
            burst_on_a_only(
                stream_a=tb.b_init,
                stream_b=tb.a_init,
                length_range=(burst_min, burst_max),
            )
        )
    # Schedule backpressure on the downstream interface
    # NOTE: This sequence continuously generates updates to the READY signal and
    #       will never complete. We don't want it to block test completion, so
    #       it is marked as `blocking=False`
    log.info("Scheduling downstream backpressure")
    tb.schedule(stream_backpressure_seq(stream=tb.x_resp), blocking=False)
