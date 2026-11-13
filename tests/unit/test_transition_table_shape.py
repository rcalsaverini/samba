"""The shape of the transition table itself (spec: states): who acts, how events are named."""

from __future__ import annotations

import re

from samba.domain.transitions import TRANSITIONS


def test_only_samba_and_the_human_act_and_both_do() -> None:
    assert {row.actor for row in TRANSITIONS} == {"samba", "human"}


def test_event_names_are_lowercase_and_dotted() -> None:
    bad = [row.event for row in TRANSITIONS if not re.fullmatch(r"[a-z_.]+", row.event)]
    assert bad == []


def test_human_events_are_namespaced_and_samba_events_are_not() -> None:
    for row in TRANSITIONS:
        assert ("." in row.event) == (row.actor == "human"), row
