Most testbenches require two types of component to operate:

 * Drivers stimulate interfaces on the design according to the implementation's
   signalling protocols. They convert transactions from the representation used
   by the testbench into the state of the different signals on the boundary of
   the design.

 * Monitors act in the opposite way to drivers, monitoring the signals wiggling
   on the boundary of the design and capturing those into transactions that the
   testbench analyses.

Different interfaces will require custom drivers and monitors, but there is a
common core of shared functionality - this is why Forastero provides two base
classes `BaseDriver` and `BaseMonitor`.

## Transactions

Forastero expects drivers and monitors to consume or produce a standard form of
transaction that is based on Python's
[dataclasses](https://docs.python.org/3/library/dataclasses.html) library. A
custom base class (`BaseTransaction`) is provided that helps Forastero interact
with these components.

For example, a transaction for driving requests on an address mapped interface
to a memory may look something like the following:

```python
import dataclasses
from enum import IntEnum, auto

from forastero import BaseTransaction

class MappedAccess(IntEnum):
    READ  = auto()
    WRITE = auto()

@dataclasses.dataclass(kw_only=True)
class MappedRequest(BaseTransaction):
    address : int = 0
    access  : MappedAccess = MappedAccess.READ
    data    : int = 0
```

The `MappedRequest` transaction is decorated by `dataclass` to mark it as a
dataclass object (see the Python documentation for more details), but importantly
also inherits from `BaseTransaction`. This base class provides a standard entry
called `timestamp` that is used to capture when the transaction was submitted to
or captured from the design, it is excluded from comparisons and exists primarily
for debug.
