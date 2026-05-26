"""
Skorpio internal "component" wiring.

Historically these names came from a Langflow shim, but Skorpio doesn't run
inside a Langflow runtime — these stubs only exist so the
`backend/langflow_components/*.py` modules continue to import cleanly and
the orchestrator can talk to them by attribute. Treat this file as a
minimal in-house types-and-base-class module, not an integration layer.

Two responsibilities:
  * `Data` — a thin "blob" wrapper. We standardise on a dict-payload shape
    so the components can pass typed report structures around without
    re-implementing serialisation in every component.
  * `Component` — a near-empty base class. Subclasses set their own
    attributes (workload_data, region_data, …) and implement an async
    `build_*` method that the orchestrator awaits.

The free-floating helpers (`IntInput`, `Output`, etc.) are leftover
stand-ins for Langflow's declarative input markers. They aren't read at
runtime anywhere in Skorpio; we keep them as no-ops so subclass-level
imports stay green if anyone forgets to prune them.
"""

from __future__ import annotations

from typing import Any, ClassVar


class Data:
    """Lightweight payload envelope used to shuttle dict-shaped data
    between components.

    Implemented as a plain class (not a dataclass) so equality and copy
    behaviour stay explicit and we don't accidentally inherit
    `@dataclass`'s positional-argument constructor — every callsite passes
    ``data=`` as a keyword.
    """

    __slots__ = ("data",)

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = dict(data) if data else {}

    def __repr__(self) -> str:  # pragma: no cover — debug only
        keys = ", ".join(sorted(self.data.keys()))[:80]
        return f"Data({{{keys}}})"


class Component:
    """Base class for the four ``backend/langflow_components/*`` wrappers
    around the real pipeline agents. Holds metadata only; instances pick
    up their inputs by attribute assignment from the orchestrator."""

    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    icon: ClassVar[str] = ""
    inputs: ClassVar[list[Any]] = []
    outputs: ClassVar[list[Any]] = []


# Declarative input markers. Skorpio doesn't introspect these — Langflow
# would, were we running inside it. Exposed as no-op callables so legacy
# ``IntInput(name="…")`` style lines stay valid imports without crashing.
def _input_stub(*_args: Any, **_kwargs: Any) -> None:
    return None


IntInput = _input_stub
MessageTextInput = _input_stub
DataInput = _input_stub
Output = _input_stub
