"""Shared query helpers.

The single most important function here is `paginate`. Without explicit bounds,
a client can pass `limit=999999` and pull the whole table into memory, or
`limit=-5`, which makes PostgreSQL reject the statement and surfaces as an
unhandled 500.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas.errors import jsonable_errors  # noqa: F401  re-exported

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass
class Page(Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int

    @property
    def pages(self) -> int:
        if self.limit <= 0:
            return 0
        return math.ceil(self.total / self.limit)


def paginate(
    db: Session,
    stmt,
    *,
    skip: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> Page:
    """Run `stmt` with a COUNT and sane bounds.

    Two queries: one `COUNT(*)` for the total, one for the page. The count is
    not free, but it is what lets a UI render "showing 1-20 of 137".
    """
    skip = max(0, skip)
    limit = max(1, min(limit, MAX_PAGE_SIZE))

    # `stmt` is a select() here, so its FROM clause is available directly.
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.execute(count_stmt).scalar_one()

    rows = db.execute(stmt.offset(skip).limit(limit)).scalars().unique().all()
    return Page(items=list(rows), total=total, skip=skip, limit=limit)