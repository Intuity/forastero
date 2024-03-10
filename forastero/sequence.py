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

import contextlib
from collections import defaultdict
from random import Random
from typing import Any, ClassVar, Callable, Self

from cocotb.log import SimLog
from cocotb.triggers import Lock

from .component import Component


class SeqLock:
    # Locks for components
    _COMPONENT_LOCKS: ClassVar[dict[Component, Self]] = {}
    # Named locks
    _NAMED_LOCKS: ClassVar[dict[str, Self]] = {}

    def __init__(self) -> None:
        self._lock = Lock()

    @classmethod
    def get_component_lock(cls, comp: Component) -> Self:
        if comp in cls._COMPONENT_LOCKS:
            return cls._COMPONENT_LOCKS[comp]
        else:
            cls._COMPONENT_LOCKS[comp] = (lock := SeqLock())
            return lock

    @classmethod
    def get_named_lock(cls, name: str) -> Self:
        if name in cls._NAMED_LOCKS:
            return cls._NAMED_LOCKS[name]
        else:
            cls._NAMED_LOCKS[name] = (lock := SeqLock())
            return lock


class SeqContext:


    def __init__(self, log: SimLog, random: Random) -> None:
        self.log = log
        self.random = random

    @contextlib.asynccontextmanager
    async def lock(self, *lockables: SeqLock | Component):
        for lock in lockables:
            if isinstance(lock, Component):
                comp = lock
                lock = SeqLock._COMPONENT_LOCKS[comp]
        # TODO Figure out how to lock and block other accesses, this might
        #      require a proxy wrapped around the component?
        yield True


class BaseSequence:
    """
    Wraps around a sequencing function and services lock requests and other
    integration with the testbench.

    :param fn: The sequencing function being wrapped
    """

    REGISTRY: ClassVar[dict[Callable, "BaseSequence"]] = {}
    LOCKS: ClassVar[dict[str, SeqLock]] = defaultdict(SeqLock)

    def __init__(self, fn: Callable) -> None:
        # Ensure that this wrapper is unique for the sequencing function
        assert id(fn) not in type(self).REGISTRY, "Sequencing function registered twice"
        type(self).REGISTRY[id(fn)] = self
        # Capture variables
        self._fn = fn
        self._requires: dict[str, Any] = {}
        self._locks: list[str] = []

    @property
    def name(self) -> str:
        return self._fn.__name__

    @classmethod
    def register(cls, fn: Callable | Self) -> Self:
        """
        Uniquely wrap a sequencing function inside a BaseSequence, returning the
        shared instance on future invocations.

        :param fn: The sequencing function
        :returns:  The wrapping BaseSequence instance
        """
        if isinstance(fn, BaseSequence):
            return fn
        elif id(fn) in cls.REGISTRY:
            return cls.REGISTRY[id(fn)]
        else:
            return BaseSequence(fn)

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
        :returns:      Tuple of the sequence name and the wrapped coroutine
        """
        # Check that provided components match expectation
        comps = {}
        for name, ctype in self._requires.items():
            # Check for a missing keyword argument
            if name not in kwds:
                raise Exception(f"No component provided for '{name}'")
            # Check if the expected component type matches
            match = kwds[name]
            if not isinstance(match, ctype):
                raise Exception(f"Component '{name}' is not of type {ctype.__name__}")
            # Pickup the component
            comps[name] = match
            # Delete from kwds (to avoid clash during expansion below)
            del kwds[name]
            # Ensure a component lock exists
            SeqLock.get_component_lock(match)
        # Generate named locks
        locks = {}
        for lock in self._locks:
            locks[lock] = SeqLock.get_named_lock(lock)
        # Create a wrapper to allow log and random to be inserted by the bench
        def _inner(log: SimLog, random: Random):
            # Create a context
            ctx = SeqContext(log, random)
            # Call the sequence
            return self._fn(ctx, **comps, **locks, **kwds)
        # Return tuple
        return (self.name, _inner)


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
