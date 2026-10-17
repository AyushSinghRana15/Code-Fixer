"""Job events. The CLI renders them now; the API will stream the same events over SSE later."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    type: str  # e.g. "phase.started", "tool.call", "tests.ran", "provider.switched"
    data: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)


EventSink = Callable[[Event], None]


class EventBus:
    """Fan-out to any number of sinks (CLI renderer, trajectory log, ...)."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks: list[EventSink] = list(sinks)
        self._lock = threading.Lock()  # several agents emit from different threads

    def add(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    def emit(self, type: str, **data: Any) -> None:
        event = Event(type, data)
        with self._lock:
            for sink in self._sinks:
                sink(event)
