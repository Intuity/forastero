Forastero expects drivers and monitors to consume or produce a standard form of
transaction that is based on Python's
[dataclasses](https://docs.python.org/3/library/dataclasses.html) library. A
custom base class ([BaseTransaction](#forastero.transaction.BaseTransaction)) is
provided that helps Forastero interact with these components.

For example, a transaction for driving requests on an address mapped interface
to a memory may look something like the following:

```python title="tb/mapped/transaction.py"
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
also inherits from [BaseTransaction](#forastero.transaction.BaseTransaction).
This base class provides a standard entry called `timestamp` that is used to
capture when the transaction was submitted to or captured from the design, it is
excluded from comparisons and exists primarily for debug.

---

::: forastero.transaction.BaseTransaction
    options:
      show_root_heading: true
      heading_level: 2
      show_source: false
