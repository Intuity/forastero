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
    timestamp: int = dataclasses.field(
        default_factory=lambda: get_sim_time(units="ns"), compare=False
    )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BaseTransaction):
            return self.compare(other)
        else:
            return super().__eq__(other)

    def format(self, field: str, value: Any) -> str:  # noqa: A003
        del field
        if isinstance(value, int):
            return f"0x{value:X}"
        else:
            return value

    def difference(self, other: "BaseTransaction") -> dict[str, tuple[Any, Any]]:
        diff = {}
        for field in dataclasses.fields(self):
            if field.compare:
                a_val = getattr(self, field.name)
                b_val = getattr(other, field.name)
                if a_val != b_val:
                    diff[field.name] = (a_val, b_val)
        return diff

    def compare(self, other: "BaseTransaction") -> bool:
        return not self.difference(other)

    def tabulate(self, other: "BaseTransaction") -> bool:
        rows = []
        for field in dataclasses.fields(self):
            a_val = self.format(field.name, getattr(self, field.name))
            b_val = self.format(field.name, getattr(other, field.name))
            flag = ["", "!!!"][field.compare and (a_val != b_val)]
            rows.append((field.name, a_val, b_val, flag))
        return tabulate(
            rows, headers=["Field", "Captured", "Expected", "Match?"], tablefmt="grid"
        )
