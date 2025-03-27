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

import asyncio
from collections import defaultdict
from collections.abc import Callable
from enum import Enum
from typing import Any

import cocotb
from cocotb.triggers import Event


class EventEmitter:
    """Core support for publishing events and subscribing to them"""

    def __init__(self) -> None:
        self._handlers = defaultdict(list)
        self._ready = Event()
        self._waiting = defaultdict(list)

    def subscribe(self, event: Enum, callback: Callable) -> None:
        """
        Subscribe to an event being published by this component.

        :param event:    Enumerated event
        :param callback: Method to call when the event occurs, this must accept
                         arguments of component, event type, and an associated
                         object
        """
        if not isinstance(event, Enum):
            raise TypeError(f"Event should inherit from Enum, unlike {event}")
        self._handlers[event].append(callback)

    def subscribe_all(self, callback: Callable) -> None:
        """
        Subscribe to all events published by this component.

        :param callback: Method to call when the event occurs, this must accept
                         arguments of component, event type, and an associated
                         object
        """
        self._handlers["*"].append(callback)

    def unsubscribe_all(self, event: Enum | None = None) -> None:
        """
        De-register all subscribers for a given event (when event is not None),
        or all subscribers from all events (when event is None).

        :param event: Optional enumerated event to unsubscribe, or None to
                      unsubscribe all subscribers for all events
        """
        if event is None:
            self._handlers.clear()
            self._waiting.clear()
        elif not isinstance(event, Enum):
            raise TypeError(f"Event should inherit from Enum, unlike {event}")
        else:
            self._handlers[event].clear()
            self._waiting[event].clear()

    def publish(self, event: Enum, obj: Any) -> None:
        """
        Publish an event and deliver it to any registered subscribers.

        :param event: Enumerated event
        :param obj:   Object associated to the event
        """
        # Call direct handlers
        for handler in self._handlers["*"] + self._handlers[event]:
            call = handler(self, event, obj)
            if asyncio.iscoroutine(call):
                cocotb.start_soon(call)
        # Trigger pending events
        events = self._waiting[event][:]
        self._waiting[event].clear()
        for event in events:
            event.set(data=obj)

    def _get_wait_event(self, event: Enum) -> Event:
        """
        Internal method for generating cocotb Events tied to a specific enumerated
        event trigger.

        :param event: Enumerated event trigger
        :returns:     The registered cocotb Event
        """
        evt = Event()
        self._waiting[event].append(evt)
        return evt

    async def wait_for(self, event: Enum) -> Any:
        """
        Wait for a specific enumerated event to occur and return the data that
        was associated to it.

        :param event: Enumerated event trigger
        :returns:     Data associated with the event
        """
        evt = self._get_wait_event(event)
        await evt.wait()
        return evt.data
