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

from collections.abc import Callable
from enum import IntEnum
from typing import Any

from cocotb.handle import HierarchyObject, NonHierarchyObject
from cocotb.log import SimLog


class IORole(IntEnum):
    """Role that a particular bus is performing (determines signal suffix)"""

    INITIATOR = 0
    RESPONDER = 1

    @staticmethod
    def opposite(value: "IntEnum") -> "IntEnum":
        return {IORole.INITIATOR: IORole.RESPONDER, IORole.RESPONDER: IORole.INITIATOR}[value]


class SignalWrapper:
    """
    Some simulators supported by cocotb give visibility into the fields of a
    struct (e.g. Cadence Xcelium), while others only expose it as a packed
    bitvector. Forastero is built to assume the signal is a packed bitvector,
    and this wrapper class normalises the behaviour.

    :param hier: The signal hierarchy object
    """

    def __init__(self, hier: HierarchyObject | NonHierarchyObject) -> None:
        self._hier = hier

        # Recursively discover all components (in case of a nested struct)
        def _expand(level):
            if isinstance(level, HierarchyObject):
                for comp in level:
                    yield from _expand(comp)
            else:
                yield level

        all_components = list(_expand(self._hier))
        # Figure out how the bit fields pack into the bit vector, precalculating
        # the MSB, LSB, and mask to save compute later
        self._packing = []
        self._width = 0
        for comp in all_components[::-1]:
            if comp._range is None:
                c_msb, c_lsb = len(comp) - 1, 0
            else:
                c_msb, c_lsb = comp._range
            rel_msb, rel_lsb = self._width + c_msb, self._width + c_lsb
            width = len(comp)
            self._packing.append(((rel_lsb, rel_msb, (1 << width) - 1), comp))
            self._width += width

    @property
    def value(self) -> int:
        value = 0
        for (lsb, _, _), comp in self._packing:
            value |= int(comp.value) << lsb
        return value

    @value.setter
    def value(self, value: int) -> None:
        for (lsb, _, mask), comp in self._packing:
            comp.value = (value >> lsb) & mask

    @property
    def _range(self) -> tuple[int, int]:
        return 0, self._width - 1

    def __len__(self) -> int:
        return self._width


def io_prefix_style(bus: str | None, component: str, role_bus: IORole, role_comp: IORole) -> str:
    """
    Style signal names as i/o_(<BUS>_)<COMPONENT> for example i_dma_awaddr and
    o_dma_awready.

    :param bus:       Name of the bus instance or None if not required
    :param component: Name of component signal withim the bus
    :param role_bus:  Interface role of the entire bus instance
    :param role_comp: Interface role of the component within the bus
    :returns:         Complete string name
    """
    mapping = {
        (IORole.INITIATOR, IORole.INITIATOR): "o",
        (IORole.INITIATOR, IORole.RESPONDER): "i",
        (IORole.RESPONDER, IORole.INITIATOR): "i",
        (IORole.RESPONDER, IORole.RESPONDER): "o",
    }
    full_name = f"{mapping[role_bus, role_comp]}"
    if bus is not None:
        full_name += f"_{bus}"
    return f"{full_name}_{component}"


def io_suffix_style(bus: str | None, component: str, role_bus: IORole, role_comp: IORole) -> str:
    """
    Style signal names as (<BUS>_)<COMPONENT>_i/o for example dma_awaddr_i and
    dma_awready_o.

    :param bus:       Name of the bus instance or None if not required
    :param component: Name of component signal withim the bus
    :param role_bus:  Interface role of the entire bus instance
    :param role_comp: Interface role of the component within the bus
    :returns:         Complete string name
    """
    mapping = {
        (IORole.INITIATOR, IORole.INITIATOR): "o",
        (IORole.INITIATOR, IORole.RESPONDER): "i",
        (IORole.RESPONDER, IORole.INITIATOR): "i",
        (IORole.RESPONDER, IORole.RESPONDER): "o",
    }
    full_name = f"{bus}_" if bus is not None else ""
    return f"{full_name}{component}_{mapping[role_bus, role_comp]}"


def io_plain_style(bus: str | None, component: str, role_bus: IORole, role_comp: IORole) -> str:
    """
    Style signal names as (<BUS>_)<COMPONENT> for example dma_awaddr and
    dma_awready.

    :param bus:       Name of the bus instance or None if not required
    :param component: Name of component signal withim the bus
    :param role_bus:  Interface role of the entire bus instance
    :param role_comp: Interface role of the component within the bus
    :returns:         Complete string name
    """
    del role_bus
    del role_comp
    if bus is None:
        return component
    else:
        return f"{bus}_{component}"


class BaseIO:
    """
    Wraps a collection of different signals into a single interface that can be
    used by drivers and monitors to interact with the design.

    :param dut:       Pointer to the DUT boundary
    :param name:      Name of the signal - acts as a prefix
    :param role:      Role of this signal on the DUT boundary
    :param init_sigs: Signals driven by the initiator
    :param resp_sigs: Signals driven by the responder
    :param io_style:  Optionally override the default I/O naming style
    """

    DEFAULT_IO_STYLE: Callable[[str | None, str, IORole, IORole], str] = io_prefix_style

    def __init__(
        self,
        dut: HierarchyObject,
        name: str | None,
        role: IORole,
        init_sigs: list[str],
        resp_sigs: list[str],
        io_style: Callable[[str | None, str, IORole, IORole], str] | None = None,
    ) -> None:
        # Sanity checks
        assert role in IORole, f"Role {role} is not recognised"
        assert isinstance(init_sigs, list), "Initiator signals are not a list"
        assert isinstance(resp_sigs, list), "Responder signals are not a list"
        # Hold onto attributes
        self._dut = dut
        self._name = name
        self._role = role
        self._init_sigs = init_sigs[:]
        self._resp_sigs = resp_sigs[:]
        self._defaults = {}
        # If no IO style provided, adopt the default
        io_style = io_style or BaseIO.DEFAULT_IO_STYLE
        # Pickup all initiator and response signals wrapping each inside a
        # SignalWrapper to normalise its behaviour across simulators
        self.__initiators, self.__responders = {}, {}
        for comp in self._init_sigs:
            sig = io_style(self._name, comp, self._role, IORole.INITIATOR)
            if not hasattr(self._dut, sig):
                SimLog("tb").getChild(f"io.{type(self).__name__.lower()}").info(
                    f"{type(self).__name__}: Did not find I/O component {sig} on {dut}"
                )
                continue
            sig_ptr = SignalWrapper(getattr(self._dut, sig))
            self.__initiators[comp] = sig_ptr
            setattr(self, comp, sig_ptr)
        for comp in self._resp_sigs:
            sig = io_style(name, comp, self._role, IORole.RESPONDER)
            if not hasattr(self._dut, sig):
                SimLog("tb").getChild(f"io.{type(self).__name__.lower()}").info(
                    f"{type(self).__name__}: Did not find I/O component {sig} on {dut}"
                )
                continue
            sig_ptr = SignalWrapper(getattr(self._dut, sig))
            self.__responders[comp] = sig_ptr
            setattr(self, comp, sig_ptr)

    @property
    def role(self) -> IORole:
        return self._role

    @property
    def dut(self) -> HierarchyObject:
        return self._dut

    def initialise(self, role: IORole) -> None:
        """Initialise signals according to the active role"""
        for sig in (self.__initiators if role == IORole.INITIATOR else self.__responders).values():
            sig.value = 0

    def set_default(self, comp: str, value: Any) -> None:
        """
        Set the default value to be returned for a signal if it is not available.

        :param comp:  Component name
        :param value: Value to return
        """
        self._defaults[comp] = value

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
            return self._defaults.get(comp, None) if default is None else default
        else:
            raw = int(item.value)
            return (raw == 1) if len(item) == 1 else raw

    def set(self, comp: str, value: Any) -> None:
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
