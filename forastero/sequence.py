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

from random import Random
from typing import Any, ClassVar, Callable, Self

from cocotb.log import SimLog


class BaseSequence:
    """
    Wraps around a sequencing function and services lock requests and other
    integration with the testbench.

    :param fn: The sequencing function being wrapped
    """

    REGISTRY: ClassVar[dict[Callable, "BaseSequence"]] = {}

    def __init__(self, fn: Callable) -> None:
        assert id(fn) in self.REGISTRY, "Sequencing function registered twice"
        self._fn = fn
        self._requires: dict[str, Any] = {}
        self._locks: list[str] = []

    @classmethod
    def register(cls, fn: Callable) -> Self:
        """
        Uniquely wrap a sequencing function inside a BaseSequence, returning the
        shared instance on future invocations.

        :param fn: The sequencing function
        """
        if id(fn) not in cls.REGISTRY:
            cls.REGISTRY[id(fn)] = (seq := BaseSequence(fn))
            return seq
        else:
            return cls.REGISTRY[id(fn)]

    def add_requirement(self, req_name: str, req_type: Any) -> Self:
        """
        Add a requirement on a driver/monitor that must be provided by the
        testbench for the sequence to execute.

        :param req_name: Name of the driver/monitor
        :param req_type: Type of the driver/monitor
        :returns:        Self to allow for simple chaining
        """
        req_name = req_name.strip().lower().replace(" ", "_")
        assert len(req_name) > 0, "Requirement name cannot be an empty string"
        assert req_name not in self._requires, f"Requirement already placed on {req_name}"
        assert req_name not in self._locks, f"Requirement {req_name} clashes with a lock"
        self._requires[req_name] = req_type
        return self

    def add_lock(self, lock_name: str) -> Self:
        """
        Define an arbitrary lock to support simple cross-sequence co-ordination
        over resources internal to the design (that are not well captured by a
        driver or monitor requirement).

        :param lock_name: Name of the lock
        :returns:         Self to allow for simple chaining
        """
        lock_name = lock_name.strip().lower().replace(" ", "_")
        assert len(lock_name) > 0, "Lock name cannot be an empty string"
        assert lock_name not in self._locks, f"Lock '{lock_name}' has already been defined"
        assert lock_name not in self._requires, f"Lock {lock_name} clashes with a requirement"
        self._locks.append(lock_name)
        return self

    def __call__(self, **kwds):
        """
        Call the underlying sequence with any parameters that it requires, and
        launch prepare it to be launched within a managed context.

        :param **kwds: Any keyword arguments
        :return:
        """
        from .bench import BaseBench
        from .component import Component
        def _inner(tb: BaseBench,
                   log: SimLog,
                   random: Random,
                   components: dict[str, Component],
                   # TODO @peterbirch: Replace 'Any' with the lock definition
                   locks: dict[str, Any]):
            return self._fn(tb, log, random, **components, **locks, **kwds)
        return _inner


def sequence() -> BaseSequence:
    """
    Decorator used to wrap a sequencing function, for now there are no arguments
    and the argument pattern is just a placeholder for future extension.
    """

    def _inner(fn: Callable) -> Callable:
        return BaseSequence.register(fn)

    return _inner


def requires(req_name: str, req_type: Any) -> BaseSequence:
    """
    Decorator used to add a requirement to a sequencing function.

    :param req_name: Name of the driver/monitor required
    :param req_type: Type of the driver/monitor required
    :returns: Wrapped sequence
    """

    def _inner(fn: Callable) -> Callable:
        return BaseSequence.register(fn).add_requirement(req_name, req_type)

    return _inner


def lock(lock_name: str) -> BaseSequence:
    """
    Decorator used to define an arbitrary lock for a sequencing function.

    :param lock_name: Name of the lock
    :returns: Wrapped sequence
    """

    def _inner(fn: Callable) -> Callable:
        return BaseSequence.register(fn).add_lock(lock_name)

    return _inner
