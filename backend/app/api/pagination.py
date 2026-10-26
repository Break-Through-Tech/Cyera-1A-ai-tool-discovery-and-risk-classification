from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class Page[T](BaseModel):
    """One page of a record collection; ``total`` counts every matching record."""

    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class PageRequest:
    limit: int
    offset: int


def _page_request(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageRequest:
    return PageRequest(limit=limit, offset=offset)


PageParams = Annotated[PageRequest, Depends(_page_request)]
