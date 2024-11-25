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

import copy
import dataclasses
from enum import Enum
from typing import Any, Optional

from cocotb.triggers import Event
from cocotb.utils import get_sim_time
from tabulate import tabulate


@dataclasses.dataclass(kw_only=True)
class BaseTransaction:
    """
    Base transaction object type

    :param timestamp: The time at which the event occurred
    :param _f_event:  Forastero event type to trigger on
    :param _c_event:  The cocotb Event to trigger when _f_event is reached
    """

    timestamp: int = dataclasses.field(
        default_factory=lambda: get_sim_time(units="ns"), compare=False
    )

    _f_event: Enum | None = dataclasses.field(default=None, compare=False)
    _c_event: Event | None = dataclasses.field(default=None, compare=False)

    def copy(self) -> "BaseTransaction":
        return copy.copy(self)

    def format(self, field: str, value: Any) -> str:
        """
        Subclasses of BaseTransaction may override this to format different
        fields however they prefer.

        :param field: Name of the field to format
        :param value: Value to format
        :returns: A string of the formatted value
        """
        if field == "timestamp":
            return f"{value} ns"
        elif isinstance(value, Enum):
            return f"{value.name} ({int(value)})"
        elif isinstance(value, int):
            return f"0x{value:X}"
        elif hasattr(value, "__int__"):
            return f"0x{int(value):X}\n({value})"
        else:
            return str(value)

    def tabulate(self, other: Optional["BaseTransaction"] = None) -> str:
        """
        Tabulate the fields of this transaction, optionally comparing against
        the fields of another object of this same type. When comparison is
        performed, mismatches are flagged in a separate column.

        :param other: Optional transaction to compare against
        :returns: String of tabulated data
        """
        # Collect table headers
        headers = ["Field"]
        if other is None:
            headers.append("Data")
        else:
            headers += ["Captured", "Expected", "Compared?", "Match?"]
        # Assemble rows
        rows = []
        for field in dataclasses.fields(self):
            if field.name in ("_f_event", "_c_event"):
                continue
            a_val = self.format(field.name, getattr(self, field.name))
            cols = [field.name, a_val]
            if other is not None:
                b_val = self.format(field.name, getattr(other, field.name))
                flag = ["", "!!!"][field.compare and (a_val != b_val)]
                cols += [b_val, ["no", "yes"][field.compare], flag]
            rows.append(cols)
        # Render the table
        return tabulate(rows, headers=headers, tablefmt="grid")
