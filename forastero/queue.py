from typing import Any

from cocotb.triggers import Event

from .transaction import BaseTransaction


class QueueEmptyError(Exception):
    pass


class Queue:
    """
    A custom queue implementation that allows peeking onto the head of the queue,
    which assists with the implementation of funnel-type channels.
    """

    def __init__(self) -> None:
        self._entries = []
        self._on_push = None

    def __len__(self) -> int:
        return self.level

    def __getitem__(self, key) -> Any:
        return self._entries[key]

    @property
    def level(self) -> int:
        return len(self._entries)

    @property
    def on_push_event(self) -> Event:
        """Expose the event that will be fired on the next push"""
        if self._on_push is None:
            self._on_push = Event()
        return self._on_push

    def push(self, data: Any) -> None:
        """
        Push an entry into the queue, notifying any observers that have
        registered an 'on-push' event.

        :param data: Data to push into the queue
        """
        self._entries.append(data)
        if self._on_push is not None:
            self._on_push.set()
        self._on_push = None

    async def pop(self, index: int = 0) -> Any:
        """
        Pop an entry from the queue, if necessary blocking until one is available.

        :param index: Index of the item to pop
        :returns:     Object from the head of the queue
        """
        if len(self._entries) == 0:
            await self.wait()
        return self._entries.pop(index)

    def wait(self) -> None:
        """Register an 'on-push' event and wait for it to be set by a push"""
        return self.on_push_event.wait()

    async def wait_for_not_empty(self) -> None:
        """Wait until at least one entry exists in the queue"""
        if self.level == 0:
            await self.wait()

    def peek(self) -> Any:
        if len(self._entries) == 0:
            raise QueueEmptyError()
        return self._entries[0]
