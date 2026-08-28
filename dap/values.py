"""Handles, and `Debugger` values as DAP variables.

The rendering itself is not here. `runtime/debugger.py` describes a value once
-- a summary, a type, and where its children live -- and both front ends read
that description, so the terminal client and the IDE cannot end up disagreeing
about what the same variable looks like. This module only turns a description
into the shape DAP wants and hands out the numbers that let a client ask for
one more level.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from runtime.debugger import Value, ValueKind


class Handles:
    """The numbers a client uses to ask for a frame's locals or a value's fields.

    A `variablesReference` is only valid for the suspended state that produced
    it. Clients do send a straggling `variables` request after a resume, and
    answering that with values from a program which has since moved on shows
    wrong numbers as if they were right -- so every handle is dropped at each
    stop, and an old one is refused.

    Numbers are never reused, for the same reason: a recycled handle would make
    a stale request look valid.
    """

    def __init__(self):
        self._entries: Dict[int, Tuple[str, Any]] = {}
        self._frames: Dict[Tuple[str, int], int] = {}
        self._next = 1

    def clear(self) -> None:
        self._entries.clear()
        self._frames.clear()

    def frame(self, depth: int) -> int:
        """The id of a stack frame, which `scopes` is asked about."""
        return self._keyed("frame", depth)

    def locals(self, depth: int) -> int:
        """The reference for that frame's Locals scope."""
        return self._keyed("locals", depth)

    def value(self, value: Value) -> int:
        """A fresh reference for one expandable value."""
        if not value.expandable:
            return 0
        return self._store(("value", value))

    def get(self, reference: int) -> Optional[Tuple[str, Any]]:
        return self._entries.get(reference)

    def _keyed(self, kind: str, depth: int) -> int:
        """One number per frame per stop, so repeated requests agree."""
        key = (kind, depth)
        if key not in self._frames:
            self._frames[key] = self._store((kind, depth))
        return self._frames[key]

    def _store(self, entry: Tuple[str, Any]) -> int:
        reference = self._next
        self._next += 1
        self._entries[reference] = entry
        return reference


def variable(name: str, value: Value, reference: int,
             evaluate_name: str = None) -> Dict[str, Any]:
    """One entry in a `variables` response.

    `evaluateName` is only set where it would work: a bare local name, which is
    what `evaluate` accepts. A field or an element has no spelling the language
    can evaluate on its own, and offering one that fails when the user adds it
    to a watch list is worse than offering none.
    """
    body: Dict[str, Any] = {"name": name, "value": value.summary}
    body.update(_described(value, reference))
    if evaluate_name:
        body["evaluateName"] = evaluate_name
    return body


def evaluation(value: Value, reference: int) -> Dict[str, Any]:
    """The same value in the shape `evaluate` answers with: `result` rather than
    `value`, and no name -- the client knows what it asked about."""
    body: Dict[str, Any] = {"result": value.summary}
    body.update(_described(value, reference))
    return body


def _described(value: Value, reference: int) -> Dict[str, Any]:
    body: Dict[str, Any] = {"type": value.type_name,
                            "variablesReference": reference}
    if value.kind is ValueKind.ARRAY:
        body["indexedVariables"] = len(value.elements)
    return body
