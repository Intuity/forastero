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
from collections.abc import Callable, Iterable
from enum import Enum, auto
from random import Random
from typing import Any, ClassVar, Generic, Self, TypeVar

import cocotb
from cocotb.handle import ModifiableObject
from cocotb.log import SimLog
from cocotb.triggers import Event, First, Lock

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

    @classmethod
    def get_all_component_locks(cls) -> Iterable[tuple[Component, Self]]:
        """Return a list of all known component locks"""
        yield from cls._COMPONENT_LOCKS.items()

    @classmethod
    def get_all_named_locks(cls) -> Iterable[tuple[str, Self]]:
        """Return a list of all known named locks"""
        yield from cls._NAMED_LOCKS.items()

    @classmethod
    def get_all_locks(cls) -> Iterable[Self]:
        """Return a list of all known locks"""
        yield from cls._COMPONENT_LOCKS.values()
        yield from cls._NAMED_LOCKS.values()

    @classmethod
    def count_all_locks(cls) -> Iterable[Self]:
        """Return the total number of locks"""
        return len(cls._COMPONENT_LOCKS) + len(cls._NAMED_LOCKS)

    @property
    def locked(self) -> bool:
        """Check if the lock is currently taken"""
        # NOTE: Prior to 1.8.0 of cocotb 'locked' was an attribute, now it is
        #       a function that must be called
        return self._lock.locked() if callable(self._lock.locked) else self._lock.locked

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
            assert self._locked_by is context, f"Illegal attempt to unlock {self._name}"
            self._locked_by = None
            self._lock.release()
            # Raise unlock event
            SeqContext.SEQ_SHARED_EVENT.publish(SeqContextEvent.UNLOCKED, None)


class SeqRandomVariable:
    """
    Captures the definition of a random variable used in a sequence along with
    how it should be randomised.

    :param name:      Name of the variable
    :param bit_width: Randomise over a given number of bits
    :param range:     Randomise over a given range (int or float)
    :param choices:   Make a random selection from a list of choices
    """

    SUFFIXES: ClassVar[tuple[str]] = ("bit_width", "range", "choices")

    def __init__(
        self,
        name: str,
        bit_width: int | None = None,
        range: tuple[int | float, int | float] | None = None,  # noqa: A002
        choices: tuple[Any] | None = None,
    ) -> None:
        # Take references
        self.name = name.strip().replace(" ", "_")
        self.bit_width = bit_width
        self.range = range
        self.choices = choices
        # Sanity checks
        assert len(name) > 0, "Variable name cannot be an empty string"
        assert not name.endswith("_bitwidth"), "Variable name must not end with '_bitwidth'"
        assert not name.endswith("_range"), "Variable name must not end with '_range'"
        assert not name.endswith("_choices"), "Variable name must not end with '_choices'"
        assert (
            len([x for x in (bit_width, range, choices) if x is not None]) <= 1
        ), "Only one of bit width, range, or choices may be specified"
        if bit_width is not None:
            assert (
                isinstance(bit_width, int) and bit_width > 0
            ), "Bit width must be an integer value greater than zero"
        elif range is not None:
            assert (
                isinstance(range, tuple) and len(range) == 2
            ), "Range must be a tuple of two values"
            assert all(
                isinstance(x, int | float) for x in range
            ), "All entries of the range must be integer or float"
        elif choices is not None:
            assert (
                isinstance(choices, tuple) and len(choices) > 0
            ), "Choices must be a tuple of at least one value"

    @property
    def varnames(self) -> tuple[str]:
        return [self.name] + [f"{self.name}_{s}" for s in self.SUFFIXES]

    def randomise(
        self,
        random: Random,
        bit_width: int | None = None,
        range: tuple[int | float, int | float] | None = None,  # noqa: A002
        choices: tuple[Any] | None = None,
    ) -> Any:
        # If any overrides are provided, evaluate them first
        if bit_width is not None:
            return random.getrandbits(bit_width)
        elif range is not None:
            if all(isinstance(x, int) for x in range):
                return random.randrange(*range)
            else:
                return random.uniform(*range)
        elif choices is not None:
            return random.choice(choices)
        # Otherwise evaluate default behaviour
        if self.bit_width is not None:
            return random.getrandbits(self.bit_width)
        elif self.range is not None:
            if all(isinstance(x, int) for x in self.range):
                return random.randrange(*self.range)
            else:
                return random.uniform(*self.range)
        elif self.choices is not None:
            return random.choices(self.choices)
        # Should not get here!
        raise Exception("Failed to select a randomisation method")


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

    def enqueue(self, *args: Any, **kwds: Any) -> Event | None:
        """
        Forward an enqueue request through from the proxy to the wrapped driver.

        :param *args: Arguments to forward
        :param *kwds: Keyword arguments to forward
        """
        if isinstance(self._component, BaseDriver):
            if not self._holds_lock:
                raise Exception(
                    f"Attempting to enqueue into {type(self._component).__name__} "
                    f"without first acquiring the lock, instead the lock is held "
                    f"by {self._lock._locked_by}"
                )
            return self._component.enqueue(*args, **kwds)
        else:
            raise Exception(f"Cannot enqueue to '{type(self._component).__name__}'")

    @property
    def clk(self) -> ModifiableObject:
        return self._component.clk

    @property
    def rst(self) -> ModifiableObject:
        return self._component.rst

    @property
    def io(self) -> ModifiableObject:
        return self._component.io

    def idle(self) -> None:
        """Forward idle through to the wrapped component"""
        return self._component.idle()


class SeqContextEvent(Enum):
    UNLOCKED = auto()


class SeqArbiter:
    """
    Arbitrates being queuing sequences to determine which sequences can start
    based on the locks they are requesting.
    """

    def __init__(self, log: SimLog, random: Random):
        self._log = log
        self._debug = log.getEffectiveLevel() <= logging.DEBUG
        self._random = Random(random.random())
        self._queue = []
        self._evt_queue = Event()
        cocotb.start_soon(self._manage())

    async def queue_for(self, context: "SeqContext", locks: list[SeqLock]) -> None:
        """
        Queue against the arbiter for a collection of locks. The arbiter will
        schedule the sequence only once all locks can be atomically acquired.

        :param context: The sequence context queueing
        :param locks:   The list of locks required
        """
        # Queue up the context, locks it requests, and the stall event
        self._queue.append((context, locks, evt := Event()))
        # Mark a new entry as having been pushed
        self._evt_queue.set()
        # Wait for the event
        await evt.wait()

    async def _manage(self) -> None:
        """Executes in a loop to schedule sequences"""
        for idx in itertools.count():
            # Wait until something is queued up
            await self._evt_queue.wait()
            # While stuff is queued, attempt to schedule it
            while self._queue:
                # Keep track of which locks are available
                available = {x for x in SeqLock.get_all_locks() if not x.locked}
                # If no locks are available, wait for the next release
                if not available:
                    await SeqContext.SEQ_SHARED_EVENT.wait_for(SeqContextEvent.UNLOCKED)
                    continue
                # Randomise the order to process the queue
                order = list(range(len(self._queue)))
                self._random.shuffle(order)
                # Log the scheduling problem
                pre_queue, pre_free = len(self._queue), available.copy()
                # Schedule as many sequences as possible
                scheduled = []
                for idx in order:
                    # Pickup the entry
                    ctx, locks, evt = self._queue[idx]
                    # If any locks are unavailable, keep searching
                    if set(locks).difference(available):
                        continue
                    # Claim the locks on behalf of the sequence
                    for lock in locks:
                        await lock.acquire(ctx)
                        available.remove(lock)
                    # Trigger the sequence release event
                    evt.set()
                    # Remember which sequences have been scheduled
                    scheduled.append(idx)
                    # If no more locks are available, break out early
                    if not available:
                        break
                # Log what was scheduled when in debug mode
                if self._debug and (post_sched := len(scheduled)) > 0:
                    post_claim, post_diff = locks[:], pre_free.difference(locks)
                    msg = (
                        f"Scheduled {post_sched} "
                        f"({', '.join(self._queue[x][0].id for x in scheduled)}) "
                        f"out of {pre_queue} sequences, claiming {len(post_claim)} "
                        f"({', '.join(x._name for x in post_claim)}) locks"
                    )
                    if len(post_diff) > 0:
                        self._log.debug(
                            f"{msg} leaving {len(post_diff)} "
                            f"({', '.join(x._name for x in post_diff)})"
                        )
                    else:
                        self._log.debug(msg)
                # Prune the scheduled sequences
                self._queue = [x for i, x in enumerate(self._queue) if i not in scheduled]
                # If scheduling was unsuccessful then either wait for locks to
                # be released or new sequences to be scheduled
                # NOTE: As the scheduling loop contains an `await` it is
                #       possible for new sequences to be queued up after the
                #       initial "order" is determined. This is why the code below
                #       only waits if no sequences were successfully scheduled.
                if not scheduled:
                    # Clear trigger event so that the next queue_for raises it
                    self._evt_queue.clear()
                    await First(
                        SeqContext.SEQ_SHARED_EVENT._get_wait_event(
                            SeqContextEvent.UNLOCKED
                        ).wait(),
                        self._evt_queue.wait(),
                    )
            # Clear the trigger event so that the next queue_for call retriggers
            # the scheduling routine
            self._evt_queue.clear()


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

    def __init__(
        self,
        sequence: "BaseSequence",
        log: SimLog,
        random: Random,
        arbiter: SeqArbiter,
        clk: ModifiableObject,
        rst: ModifiableObject,
    ) -> None:
        self._sequence = sequence
        self._arbiter = arbiter
        # Allocate an ID unique to the sequence's name
        self._ctx_id = next(type(self).SEQ_CTX_ID[self._sequence.name])
        # Fork the log to ensure a distinct context
        self.log = log.getChild(self.id)
        # Fork the root random to ensure sequence run-to-run consistency
        self.random = Random(random.random())
        # Reference clock and reset
        self.clk = clk
        self.rst = rst
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
        assert not self._locks_active, "You must release all locks before re-acquisition"
        self._locks_active = True
        # Figure out all the locks that need to be acquired
        need: list[SeqLock] = []
        for lock in lockables:
            if isinstance(lock, SeqProxy):
                need.append(SeqLock.get_component_lock(lock._component))
            else:
                need.append(lock)
        # Queue against the arbiter for a slot to execute
        await self._arbiter.queue_for(self, need)
        # Yield to allow the sequence to execute
        yield
        # Release any remaining locks
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
        self._randargs: dict[str, SeqRandomVariable] = {}

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

    def add_randarg(
        self,
        name: str,
        bit_width: int | None = None,
        range: tuple[int | float, int | float] | None = None,  # noqa: A002
        choices: tuple[Any] | None = None,
    ) -> Self:
        """
        Define an argument that can be randomised in a number of different ways.
        Only one method of randomisation may be specified.

        :param name:      Name of the argument
        :param bit_width: Randomise over a given number of bits
        :param range:     Randomise over a given range (int or float)
        :param choices:   Make a random selection from a list of choices
        :returns:         Self to allow for simple chaining
        """
        rv = SeqRandomVariable(name, bit_width, range, choices)
        self._randargs[rv.name] = rv
        return self

    def __call__(self, **kwds):
        """
        Call the underlying sequence with any parameters that it requires, and
        launch prepare it to be launched within a managed context.

        :param **kwds: Any keyword arguments
        :returns:      The wrapped coroutine
        """

        # Create a wrapper to allow log and random to be inserted by the bench
        async def _inner(
            log: SimLog,
            random: Random,
            arbiter: SeqArbiter,
            clk: ModifiableObject,
            rst: ModifiableObject,
        ):
            # Create a context
            ctx = SeqContext(self, log, random, arbiter, clk, rst)
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
            # Identify random arguments and overrides
            arguments = {}
            for name, rv in self._randargs.items():
                # Identify any matching overrides
                overrides = [(k, v) for k, v in kwds.items() if k in rv.varnames]
                assert len(overrides) in (0, 1), (
                    f"Expecting a maximum of one override for {name}, instead "
                    f"found: {', '.join(x[0] for x in overrides)}"
                )
                # If not overridden, immediately randomise
                if not overrides:
                    arguments[name] = rv.randomise(ctx.random)
                    continue
                # Determine override mode
                o_name, o_val = overrides[0]
                for sfx in SeqRandomVariable.SUFFIXES:
                    if o_name.endswith("_" + sfx):
                        arguments[name] = rv.randomise(ctx.random, **{sfx: o_val})
                        break
                # If no override mode was matched, this is a fixed value
                else:
                    arguments[name] = o_val
                # Delete from kwds
                del kwds[o_name]
            # Fill in all remaining values
            for name, value in kwds.items():
                arguments[name] = value
            # Log what's about to launch
            ctx.log.debug(f"Launching {ctx.id} with arguments: {arguments}")
            # If auto-locking requested, wrap with a lock context
            if self.auto_lock:
                async with ctx.lock(*comps.values(), *locks.values()):
                    await self._fn(ctx, **comps, **locks, **arguments)
            # Otherwise just launch the sequence directly
            else:
                await self._fn(ctx, **comps, **locks, **arguments)

        # Return wrapped coroutine
        return self, _inner


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


def randarg(
    name: str,
    bit_width: int | None = None,
    range: tuple[int | float, int | float] | None = None,  # noqa: A002
    choices: tuple[Any] | None = None,
) -> BaseSequence:
    """
    Decorator used to add a randomised argument to a sequence definition, that
    can be randomised in a number of different ways. Only one method of
    randomisation may be specified.

    :param name:      Name of the argument
    :param bit_width: Randomise over a given number of bits
    :param range:     Randomise over a given range (int or float)
    :param choices:   Make a random selection from a list of choices
    :returns:         Wrapped sequence
    """

    def _inner(fn: Callable) -> Callable:
        return BaseSequence.register(fn).add_randarg(
            name=name, bit_width=bit_width, range=range, choices=choices
        )

    return _inner
