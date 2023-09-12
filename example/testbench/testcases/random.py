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


from ..stream import StreamBackpressure, StreamTransaction
from ..testbench import Testbench


@Testbench.testcase()
async def random(tb: Testbench):
    # Disable backpressure on input
    tb.x_resp.enqueue(StreamBackpressure(ready=True))
    # Queue random traffic onto interfaces A & B
    for _ in range(100):
        tb.a_init.enqueue(a := StreamTransaction(data=tb.random.getrandbits(32)))
        tb.b_init.enqueue(b := StreamTransaction(data=tb.random.getrandbits(32)))
        del a
        del b
