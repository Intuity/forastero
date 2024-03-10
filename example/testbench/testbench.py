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

from cocotb.handle import HierarchyObject

from forastero.bench import BaseBench
from forastero.driver import DriverEvent
from forastero.io import IORole

from .stream import StreamInitiator, StreamIO, StreamMonitor, StreamResponder, StreamTransaction


class Testbench(BaseBench):
    """
    Testbench wrapped around the simple 2-to-1 stream arbiter.

    :param dut: Reference to the arbiter DUT
    """

    def __init__(self, dut: HierarchyObject) -> None:
        super().__init__(
            dut,
            clk=dut.i_clk,
            rst=dut.i_rst,
            clk_drive=True,
            clk_period=1,
            clk_units="ns",
        )
        # Wrap stream I/O on the arbiter
        a_io = StreamIO(dut, "a", IORole.RESPONDER)
        b_io = StreamIO(dut, "b", IORole.RESPONDER)
        x_io = StreamIO(dut, "x", IORole.INITIATOR)
        # Register drivers and monitors for the stream interfaces
        self.register("a_init", StreamInitiator(self, a_io, self.clk, self.rst))
        self.register("b_init", StreamInitiator(self, b_io, self.clk, self.rst))
        self.register(
            "x_resp", StreamResponder(self, x_io, self.clk, self.rst, blocking=False)
        )
        self.register(
            "x_mon",
            StreamMonitor(self, x_io, self.clk, self.rst),
            scoreboard_queues=["a", "b"],
        )
        # Register callbacks to the model
        self.a_init.subscribe(DriverEvent.POST_DRIVE, self.model)
        self.b_init.subscribe(DriverEvent.POST_DRIVE, self.model)

    def model(self,
              driver: StreamInitiator,
              event: DriverEvent,
              obj: StreamTransaction) -> None:
        assert driver in (self.a_init, self.b_init)
        assert event == DriverEvent.POST_DRIVE
        if driver is self.a_init:
            self.scoreboard.channels["x_mon"].push_reference("a", obj)
        else:
            self.scoreboard.channels["x_mon"].push_reference("b", obj)
