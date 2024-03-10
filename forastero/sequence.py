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
import itertools
import logging
from collections import defaultdict
from enum import Enum
from random import Random
from typing import Any, ClassVar, Callable, Self

from cocotb.log import SimLog
from cocotb.triggers import Lock

from .component import Component
from .driver import BaseDriver
from .event import EventEmitter


class SeqLock:
    # Locks for components
    _COMPONENT_LOCKS: ClassVar[dict[Component, Self]] = {}
    # Named locks
    _NAMED_LOCKS: ClassVar[dict[str, Self]] = {}

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = Lock()
        self._locked_by: BaseSequence | None = None

    @classmethod
    def get_component_lock(cls, comp: Component) -> Self:
        if comp in cls._COMPONENT_LOCKS:
            return cls._COMPONENT_LOCKS[comp]
        else:
            cls._COMPONENT_LOCKS[comp] = (lock := SeqLock(comp.name))
            return lock

    @classmethod
    def get_named_lock(cls, name: str) -> Self:
        if name in cls._NAMED_LOCKS:
            return cls._NAMED_LOCKS[name]
        else:
            cls._NAMED_LOCKS[name] = (lock := SeqLock(name))
            return lock

    async def lock(self, sequence: "SeqContext") -> None:
        if self._lock.locked and self._locked_by is sequence:
            return
        else:
            await self._lock.acquire()
            logging.getLogger(f"tb.seqlock.{self._name}").info(
                f"Lock {id(self._lock)} acquired by {sequence.id}"
            )
            self._locked_by = sequence

    def release(self, sequence: "SeqContext") -> None:
        if self._lock.locked:
            assert self._locked_by is sequence
            logging.getLogger(f"tb.seqlock.{self._name}").info(
                f"Lock {id(self._lock)} released by {sequence.id}"
            )
            self._locked_by = None
            self._lock.release()


class SeqProxy(EventEmitter):
    """
    Wraps around a component to provide locking and masking functionality, this
    is achieved by mocking functionality of a component including intercepting
    and filtering events.

    :param sequence:  The sequence that owns this proxy
    :param component: The component to proxy
    :param lock:      The shared lock for the component
    """

    def __init__(self,
                 ctx: "SeqContext",
                 component: Component,
                 lock: SeqLock) -> None:
        super().__init__()
        self._context = ctx
        self._component = component
        self._lock = lock
        # Subscribe to events from the component
        self._component.subscribe_all(self._event_callback)

    @property
    def _holds_lock(self) -> bool:
        return self._lock._lock.locked and self._lock._locked_by is self._context

    def _event_callback(self, comp: Component, event: Enum, obj: Any) -> None:
        """
        Intercepts all events coming from the component and drops them if the
        lock is held by another sequence.

        :param comp:  Component emitting the event
        :param event: The event being emitted
        :param obj:   The event object
        """
        if not self._lock._lock.locked or self._holds_lock:
            self.publish(event, obj)

    def enqueue(self, *obj: Any) -> None:
        """
        Forward an enqueue request through from the proxy to the wrapped driver.

        :param *obj: The object(s) to enqueue
        """
        if isinstance(self._component, BaseDriver):
            if not self._holds_lock:
                raise Exception(
                    f"Attempting to enqueue into {type(self._component).__name__} "
                    f"without first acquiring the lock, instead the lock is held "
                    f"by {self._lock._locked_by}"
                )
            self._component.enqueue(*obj)
        else:
            raise Exception(f"Cannot enqueue to '{type(self._component).__name__}'")

    def idle(self) -> None:
        """Forward idle through to the wrapped component"""
        return self._component.idle()


class SeqContext:

    SEQ_CTX_ID = itertools.count()

    def __init__(self, sequence: "BaseSequence", log: SimLog, random: Random) -> None:
        self._sequence = sequence
        self._ctx_id = next(type(self).SEQ_CTX_ID)
        self.log = log.getChild(self.id)
        self.random = random

    @property
    def id(self) -> str:
        return f"{self._sequence.name}[{self._ctx_id}]"

    @contextlib.asynccontextmanager
    async def lock(self, *lockables: SeqLock | SeqProxy):
        held = []
        # Acquire all locks
        self.log.info(f"Acquiring {len(lockables)} locks: ")
        for lock in lockables:
            # For components, first resolve to get the component lock
            if isinstance(lock, SeqProxy):
                lock = SeqLock.get_component_lock(lock._component)
            await lock.lock(self)
            held.append(lock)
        # Yield the requested locks
        self.log.info("Yielding to the sequence")
        yield
        # Release the locks
        self.log.info(f"Releasing {len(lockables)} locks")
        for lock in held:
            lock.release(self)


class BaseSequence:
    """
    Wraps around a sequencing function and services lock requests and other
    integration with the testbench.

    :param fn: The sequencing function being wrapped
    """

    REGISTRY: ClassVar[dict[Callable, "BaseSequence"]] = {}
    LOCKS: ClassVar[dict[str, SeqLock]] = defaultdict(SeqLock)
    ACTIVE: ClassVar[int] = 0

    def __init__(self, fn: Callable) -> None:
        # Ensure that this wrapper is unique for the sequencing function
        assert id(fn) not in type(self).REGISTRY, "Sequencing function registered twice"
        type(self).REGISTRY[id(fn)] = self
        # Capture variables
        self._fn = fn
        self._requires: dict[str, Any] = {}
        self._locks: list[str] = []

    def __repr__(self) -> str:
        return f"<BaseSequence name=\"{self.name}\">"

    @classmethod
    def get_active(cls) -> int:
        return cls.ACTIVE

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
        :returns:      The wrapped coroutine
        """
        # Create a wrapper to allow log and random to be inserted by the bench
        async def _inner(log: SimLog, random: Random, blocking: bool):
            # Increment active as the sequence starts
            # TODO: Improve how this shutdown hold-off mechanism is working
            if blocking:
                type(self).ACTIVE += 1
            # Create a context
            ctx = SeqContext(self, log, random)
            # Check that provided components match expectation
            comps = {}
            for name, ctype in self._requires.items():
                # Check for a missing keyword argument
                if name not in kwds:
                    raise Exception(f"No component provided for '{name}'")
                # Check if the expected component type matches
                # NOTE: Delete from kwds to avoid clash during expansions
                match = kwds[name]
                del kwds[name]
                if not isinstance(match, ctype):
                    raise Exception(f"Component '{name}' is not of type {ctype.__name__}")
                # Ensure a component lock exists
                comp_lock = SeqLock.get_component_lock(match)
                # Pickup the component and wrap it in a proxy
                comps[name] = SeqProxy(ctx, match, comp_lock)
            # Generate named locks
            locks = {}
            for lock in self._locks:
                locks[lock] = SeqLock.get_named_lock(lock)
            # Call the sequence
            await self._fn(ctx, **comps, **locks, **kwds)
            # Decrement active
            if blocking:
                type(self).ACTIVE -= 1
        # Return wrapped coroutine
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
