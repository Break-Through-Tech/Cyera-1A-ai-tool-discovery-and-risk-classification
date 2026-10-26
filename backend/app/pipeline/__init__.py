from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import Engine


@dataclass(frozen=True)
class RunContext:
    """What a phase may use while analyzing one Batch within one Analysis Run."""

    run_id: str
    batch_id: str
    engine: Engine


@dataclass(frozen=True)
class Phase:
    name: str
    run: Callable[[RunContext], None]


@dataclass(frozen=True)
class Pipeline:
    """The ordered analysis phases and the versions an Analysis Run records for them."""

    phases: tuple[Phase, ...] = ()
    versions: Mapping[str, str] = field(default_factory=dict)


def default_pipeline() -> Pipeline:
    return Pipeline()
