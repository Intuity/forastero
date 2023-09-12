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

import dataclasses
from typing import Any

from cocotb.utils import get_sim_time
from tabulate import tabulate


@dataclasses.dataclass(kw_only=True)
class BaseTransaction:
    """Base transaction object type"""

    timestamp: int = dataclasses.field(
        default_factory=lambda: get_sim_time(units="ns"), compare=False
    )

    def format(self, field: str, value: Any) -> str:  # noqa: A003
        """
        Subclasses of BaseTransaction may override this to format different
        fields however they prefer.

        :param field: Name of the field to format
        :param value: Value to format
        :returns: A string of the formatted value
        """
        if field == "timestamp":
            return f"{value} ns"
        elif isinstance(value, int):
            return f"0x{value:X}"
        else:
            return value

    def tabulate(self, other: "BaseTransaction") -> str:
        """
        Tabulate a comparison of the fields of the transaction against another
        object, flagging wherever a mismatch is detected.

        :param other: The 'other' transaction
        :returns: String of tabulated data
        """
        rows = []
        for field in dataclasses.fields(self):
            a_val = self.format(field.name, getattr(self, field.name))
            b_val = self.format(field.name, getattr(other, field.name))
            flag = ["", "!!!"][field.compare and (a_val != b_val)]
            rows.append((field.name, a_val, b_val, ["no", "yes"][field.compare], flag))
        return tabulate(
            rows,
            headers=["Field", "Captured", "Expected", "Compared?", "Match?"],
            tablefmt="grid",
        )
