
## Defining Sequences

```python title="tb/sequences/stream_seq.py"
from random import Random

import forastero
from cocotb.log import SimLog
from forastero import SeqLock

from ..stream import StreamInitiator, StreamMonitor
from ..testbench import Testbench

@forastero.sequence()
@forastero.requires("stream_a", StreamInitiator)
@forastero.requires("stream_b", StreamMonitor)
@forastero.lock("pathway_a")
async def stream_fast(log: SimLog,
                      random: Random,
                      stream_a: StreamInitiator,
                      stream_b: StreamMonitor,
                      pathway_a: SeqLock):
    ...
```
