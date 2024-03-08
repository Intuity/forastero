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

from enum import IntEnum
from typing import Any

from cocotb.log import SimLog
from cocotb.handle import HierarchyObject


class IORole(IntEnum):
    """Role that a particular bus is performing (determines signal suffix)"""

    INITIATOR = 0
    RESPONDER = 1

    @staticmethod
    def opposite(value: "IntEnum") -> "IntEnum":
        return {IORole.INITIATOR: IORole.RESPONDER, IORole.RESPONDER: IORole.INITIATOR}[
            value
        ]


class BaseIO:
    """
    Wraps a collection of different signals into a single interface that can be
    used by drivers and monitors to interact with the design.

    :param dut      : Pointer to the DUT boundary
    :param name     : Name of the signal - acts as a prefix
    :param role     : Role of this signal on the DUT boundary
    :param init_sigs: Signals driven by the initiator
    :param resp_sigs: Signals driven by the responder
    """

    def __init__(
        self,
        dut: HierarchyObject,
        name: str,
        role: IORole,
        init_sigs: list[str],
        resp_sigs: list[str],
    ) -> None:
        # Sanity checks
        assert role in IORole, f"Role {role} is not recognised"
        assert isinstance(init_sigs, list), "Initiator signals are not a list"
        assert isinstance(resp_sigs, list), "Responder signals are not a list"
        # Hold onto attributes
        self.__dut = dut
        self.__name = name
        self.__role = role
        self.__init_sigs = init_sigs[:]
        self.__resp_sigs = resp_sigs[:]
        self.__defaults = {}
        # Pickup attributes
        self.__initiators, self.__responders = {}, {}
        for comp in self.__init_sigs:
            sig = "o" if self.__role == IORole.INITIATOR else "i"
            if self.__name is not None:
                sig += f"_{self.__name}"
            sig += f"_{comp}"
            if not hasattr(self.__dut, sig):
                SimLog("tb").getChild(f"io.{type(self).__name__.lower()}").info(
                    f"{type(self).__name__}: Did not find I/O component {sig} on {dut}"
                )
                continue
            sig_ptr = getattr(self.__dut, sig)
            self.__initiators[comp] = sig_ptr
            setattr(self, comp, sig_ptr)
        for comp in self.__resp_sigs:
            sig = "i" if self.__role == IORole.INITIATOR else "o"
            if self.__name is not None:
                sig += f"_{self.__name}"
            sig += f"_{comp}"
            if not hasattr(self.__dut, sig):
                SimLog("tb").getChild(f"io.{type(self).__name__.lower()}").info(
                    f"{type(self).__name__}: Did not find I/O component {sig} on {dut}"
                )
                continue
            sig_ptr = getattr(self.__dut, sig)
            self.__responders[comp] = sig_ptr
            setattr(self, comp, sig_ptr)

    @property
    def role(self) -> IORole:
        return self.__role

    @property
    def dut(self) -> HierarchyObject:
        return self.__dut

    def initialise(self, role: IORole) -> None:
        """Initialise signals according to the active role"""
        for sig in (
            self.__initiators if role == IORole.INITIATOR else self.__responders
        ).values():
            sig.value = 0

    def set_default(self, comp: str, value: Any) -> None:
        """
        Set the default value to be returned for a signal if it is not available.

        :param comp:  Component name
        :param value: Value to return
        """
        self.__defaults[comp] = value

    def has(self, comp: str) -> bool:
        """
        Test whether a particular signal has been resolved inside the interface.

        :param comp: Name of the component
        :returns:    True if exists, False otherwise
        """
        return (comp in self.__initiators) or (comp in self.__responders)

    def get(self, comp: str, default: Any = None) -> Any:
        """
        Get the current value of a particular signal.

        :param comp:    Name of the component
        :param default: Default value if the signal is not resolved
        :returns:       The resolved value, otherwise the default
        """
        item = getattr(self, comp, None)
        if item is None:
            return self.__defaults.get(comp, None) if default is None else default
        else:
            raw = int(item.value)
            return (raw == 1) if len(item) == 1 else raw

    def set(self, comp: str, value: Any) -> None:  # noqa: A003
        """
        Set the value of a particular signal if it exists.

        :param comp:  Name of the component
        :param value: Value to set
        """
        if not self.has(comp):
            return
        getattr(self, comp).value = value

    def width(self, comp: str) -> int:
        """
        Return the width of a particular signal.

        :param comp: Name of the component
        :returns:    The bit width if resolved, else 0
        """
        if not self.has(comp):
            return 0
        sig = getattr(self, comp)
        return max(sig._range) - min(sig._range) + 1
