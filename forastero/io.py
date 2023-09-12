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
    """Base I/O wrapper class"""

    def __init__(self, dut, name, role, init_sigs, resp_sigs):
        """Initialise BaseIO.

        Args:
            dut      : Pointer to the DUT boundary
            name     : Name of the signal - acts as a prefix
            role     : Role of this signal on the DUT boundary
            init_sigs: Signals driven by the initiator
            resp_sigs: Signals driven by the responder
        """
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
        # Pickup attributes
        self.__initiators, self.__responders = {}, {}
        for comp in self.__init_sigs:
            sig = "o" if self.__role == IORole.INITIATOR else "i"
            sig += f"_{self.__name}_{comp}"
            if not hasattr(self.__dut, sig):
                dut._log.info(
                    f"{type(self).__name__}: Did not find I/O component {sig} on {dut}"
                )
                continue
            sig_ptr = getattr(self.__dut, sig)
            self.__initiators[comp] = sig_ptr
            setattr(self, comp, sig_ptr)
        for comp in self.__resp_sigs:
            sig = "i" if self.__role == IORole.INITIATOR else "o"
            sig += f"_{self.__name}_{comp}"
            if not hasattr(self.__dut, sig):
                dut._log.info(
                    f"{type(self).__name__}: Did not find I/O component {sig} on {dut}"
                )
                continue
            sig_ptr = getattr(self.__dut, sig)
            self.__responders[comp] = sig_ptr
            setattr(self, comp, sig_ptr)

    @property
    def role(self):
        return self.__role

    def initialise(self, role):
        """Initialise signals according to the active role"""
        for sig in (
            self.__initiators if role == IORole.INITIATOR else self.__responders
        ).values():
            sig.value = 0

    def has(self, comp):
        return (comp in self.__initiators) or (comp in self.__responders)

    def get(self, comp, default=None):
        item = getattr(self, comp, None)
        if item is None:
            return default
        else:
            raw = int(item.value)
            return (raw == 1) if len(item) == 1 else raw

    def set(self, comp, value):  # noqa: A003
        if not self.has(comp):
            return
        getattr(self, comp).value = value

    def width(self, comp):
        if not self.has(comp):
            return 0
        sig = getattr(self, comp)
        return max(sig._range) - min(sig._range) + 1
