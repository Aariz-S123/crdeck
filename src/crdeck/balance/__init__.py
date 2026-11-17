"""Balance updates: the calendar of when cards changed, and what follows from it.

- events: config/balance/events.yaml, loaded and checked.
- flags:  which cards of a deck changed during or after the battles a model's numbers were measured on
          (the state crdeck.explain names STALE_AFTER_BALANCE).

A subpackage on purpose: crdeck.pipeline._fingerprint hashes only the top-level src/crdeck/*.py and
config/*.yaml, so nothing here can force a retrain.
"""

from .events import Calendar, Change, Event, EventsError, card_labels, from_web_json, last_event_before, load_events, web_json
from .flags import stale_flags

__all__ = ["Calendar", "from_web_json", "Change", "Event", "EventsError", "card_labels", "last_event_before", "load_events", "web_json", "stale_flags"]
