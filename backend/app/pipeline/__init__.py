from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine


@dataclass(frozen=True)
class RunContext:
    """What a phase may use while analyzing one Batch within one Analysis Run.

    Phases hand their outputs to later phases through ``results``; nothing derived is
    written to the database until the whole Run has succeeded.
    """

    run_id: str
    batch_id: str
    engine: Engine
    results: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Phase:
    name: str
    run: Callable[[RunContext], None]


@dataclass(frozen=True)
class Pipeline:
    """The ordered analysis phases and the versions an Analysis Run records for them."""

    phases: tuple[Phase, ...] = ()
    versions: Mapping[str, str] = field(default_factory=dict)
