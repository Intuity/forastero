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
from collections import defaultdict
from collections.abc import Callable
from enum import Enum, auto
from random import Random
from typing import Any, ClassVar, Generic, Self, TypeVar

from cocotb.log import SimLog
from cocotb.triggers import Lock

from .component import Component
from .driver import BaseDriver
from .event import EventEmitter


class SeqLock:
    """
    Wraps around cocotb's Lock primitive to also track which sequence currently
    holds the lock.

    :param name: Name of the lock
    """

    # Locks for components
    _COMPONENT_LOCKS: ClassVar[dict[Component, Self]] = {}
    # Named locks
    _NAMED_LOCKS: ClassVar[dict[str, Self]] = {}

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = Lock(name)
        self._locked_by: BaseSequence | None = None

    @classmethod
    def get_component_lock(cls, comp: Component) -> Self:
        """
        Retrieve the shared lock for a specific component.

        :param comp: Reference to the component
        :returns:    The shared lock instance
        """
        if comp in cls._COMPONENT_LOCKS:
            return cls._COMPONENT_LOCKS[comp]
        else:
            cls._COMPONENT_LOCKS[comp] = (lock := SeqLock(comp.name))
            return lock

    @classmethod
    def get_named_lock(cls, name: str) -> Self:
        """
        Retrieve a shared named lock (distinct from all component locks).

        :param name: Name of the shared lock
        :returns:    The shared lock instance
        """
        if name in cls._NAMED_LOCKS:
            return cls._NAMED_LOCKS[name]
        else:
            cls._NAMED_LOCKS[name] = (lock := SeqLock(name))
            return lock

    @property
    def locked(self) -> bool:
        """Check if the lock is currently taken"""
        return self._lock.locked

    async def acquire(self, context: "SeqContext") -> None:
        """
        Attempt to acquire a lock, waiting until it becomes available.

        :param context: Reference to the sequence context claiming the lock
        """
        assert isinstance(context, SeqContext)
        if self._lock.locked and self._locked_by is context:
            return
        else:
            await self._lock.acquire()
            self._locked_by = context

    def release(self, context: "SeqContext") -> None:
        """
        Release a held lock only if the context matches the current lock holder.

        :param context: Reference to the sequence context that previously claimed
                        the lock
        """
        assert isinstance(context, SeqContext)
        if self._lock.locked:
            assert self._locked_by is context
            self._locked_by = None
            self._lock.release()
            # Raise unlock event
            SeqContext.SEQ_SHARED_EVENT.publish(SeqContextEvent.UNLOCKED, None)


C = TypeVar("C")


class SeqProxy(EventEmitter, Generic[C]):
    """
    Wraps around a component to provide locking and masking functionality, this
    is achieved by mocking functionality of a component including intercepting
    and filtering events.

    :param context:   The sequence context associated to this proxy
    :param component: The component to proxy
    :param lock:      The shared lock for the component
    """

    def __init__(self, context: "SeqContext", component: C, lock: SeqLock) -> None:
        super().__init__()
        assert isinstance(component, Component)
        self._context = context
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


class SeqContextEvent(Enum):
    UNLOCKED = auto()


class SeqContext:
    """
    A context specific to a given sequence invocation that provides logging,
    random value generation, and lock management.

    :param sequence: The sequence being invoked
    :param log:      The root sequencing log (pre-fork)
    :param random:   The root random instance (pre-fork)
    """

    SEQ_CTX_ID: ClassVar[dict[str, itertools.count]] = defaultdict(itertools.count)
    SEQ_SHARED_LOCK: ClassVar[Lock] = Lock()
    SEQ_SHARED_EVENT: ClassVar[EventEmitter] = EventEmitter()

    def __init__(self, sequence: "BaseSequence", log: SimLog, random: Random) -> None:
        self._sequence = sequence
        # Allocate an ID unique to the sequence's name
        self._ctx_id = next(type(self).SEQ_CTX_ID[self._sequence.name])
        # Fork the log to ensure a distinct context
        self.log = log.getChild(self.id)
        # Fork the root random to ensure sequence run-to-run consistency
        self.random = Random(random.random())
        # Lock re-entrancy flag
        self._locks_active = False

    @property
    def id(self) -> str:
        return f"{self._sequence.name}[{self._ctx_id}]"

    @contextlib.asynccontextmanager
    async def lock(self, *lockables: SeqLock | SeqProxy):
        """
        Atomically acquire one or more named or component locks (i.e. locks will
        only be claimed if all locks are available, otherwise it will wait until
        such a condition can be met).

        :param *lockables: References to named locks or sequence proxies (which
                           will be resolved to the equivalent component locks)
        """
        # Mark that locking is active
        assert (
            not self._locks_active
        ), "You must release all locks before re-acquisition"
        self._locks_active = True
        # Figure out all the locks that need to be acquired
        need: list[SeqLock] = []
        for lock in lockables:
            if isinstance(lock, SeqProxy):
                need.append(SeqLock.get_component_lock(lock._component))
            else:
                need.append(lock)
        # Atomically acquire all requested locks
        self.log.debug(f"Acquiring {len(need)} locks")
        while True:
            async with type(self).SEQ_SHARED_LOCK:
                # Only claim locks if all locks are available
                if not any(x.locked for x in need):
                    for lock in need:
                        await lock.acquire(self)
                    break
            # Wait any lock to be released before re-evaluating
            await type(self).SEQ_SHARED_EVENT.wait_for(SeqContextEvent.UNLOCKED)
        # Yield the requested locks
        yield
        # Release any remaining locks
        self.log.debug(f"Releasing {len(lockables)} locks")
        for lock in need:
            if lock._locked_by is self:
                lock.release(self)
        # Clear locking active flag
        self._locks_active = False

    def release(self, *lockables: SeqLock | SeqProxy):
        """
        Release one or more named or component locks, allowing other sequences
        to move forward. Note that attempting to release a lock that the sequence
        doesn't hold will raise an exception.

        :param *lockables: References to named locks or sequence proxies (which
                           will be resolved to the equivalent component locks)
        """
        for lock in lockables:
            if isinstance(lock, SeqProxy):
                SeqLock.get_component_lock(lock._component).release(self)
            else:
                lock.release(self)


class BaseSequence:
    """
    Wraps around a sequencing function and services lock requests and other
    integration with the testbench.

    :param fn: The sequencing function being wrapped
    """

    REGISTRY: ClassVar[dict[Callable, "BaseSequence"]] = {}
    LOCKS: ClassVar[dict[str, SeqLock]] = defaultdict(SeqLock)

    def __init__(self, fn: Callable, auto_lock: bool = False) -> None:
        # Ensure that this wrapper is unique for the sequencing function
        assert id(fn) not in type(self).REGISTRY, "Sequencing function registered twice"
        type(self).REGISTRY[id(fn)] = self
        # Capture variables
        self.auto_lock = auto_lock
        self._fn = fn
        self._requires: dict[str, Any] = {}
        self._locks: list[str] = []

    def __repr__(self) -> str:
        return f'<BaseSequence name="{self.name}">'

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
        assert (
            req_name not in self._requires
        ), f"Requirement already placed on {req_name}"
        assert (
            req_name not in self._locks
        ), f"Requirement {req_name} clashes with a lock"
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
        assert (
            lock_name not in self._locks
        ), f"Lock '{lock_name}' has already been defined"
        assert (
            lock_name not in self._requires
        ), f"Lock {lock_name} clashes with a requirement"
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
        async def _inner(log: SimLog, random: Random):
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
                    raise Exception(
                        f"Component '{name}' is not of type {ctype.__name__}"
                    )
                # Ensure a component lock exists
                comp_lock = SeqLock.get_component_lock(match)
                # Pickup the component and wrap it in a proxy
                comps[name] = SeqProxy(ctx, match, comp_lock)
            # Generate named locks
            locks = {}
            for lock in self._locks:
                locks[lock] = SeqLock.get_named_lock(lock)
            # If auto-locking requested, wrap with a lock context
            if self.auto_lock:
                async with ctx.lock(*comps.values(), *locks.values()):
                    await self._fn(ctx, **comps, **locks, **kwds)
            # Otherwise just launch the sequence directly
            else:
                await self._fn(ctx, **comps, **locks, **kwds)

        # Return wrapped coroutine
        return _inner


def sequence(auto_lock: bool = False) -> BaseSequence:
    """
    Decorator used to wrap a sequencing function, for now there are no arguments
    and the argument pattern is just a placeholder for future extension.

    :param auto_lock: When enabled locks will be claimed automatically on all
                      requirements as the sequence starts, otherwise the sequence
                      will be responsible for claiming and releasing locks
    :returns:         Wrapped sequence
    """

    def _inner(fn: Callable) -> Callable:
        seq = BaseSequence.register(fn)
        seq.auto_lock = auto_lock
        return seq

    return _inner


def requires(req_name: str, req_type: Any | None = None) -> BaseSequence:
    """
    Decorator used to add a requirement on a driver/monitor or an arbitrarily
    named lock to a sequencing function.

    :param req_name: Name of the lock, driver, or monitor required
    :param req_type: Type of the driver/monitor required
    :returns:        Wrapped sequence
    """

    def _inner(fn: Callable) -> Callable:
        if req_type is None:
            return BaseSequence.register(fn).add_lock(req_name)
        else:
            return BaseSequence.register(fn).add_requirement(req_name, req_type)

    return _inner
